"""Motor de downloads thread-safe.

Arquitetura:
  - Cada download roda em sua própria daemon-thread com uma instância própria
    de yt_dlp.YoutubeDL (yt-dlp não é thread-safe entre instâncias compartilhadas).
  - Fila concorrente com limite configurável (`Configuracoes.simultaneos`).
  - Hooks de progresso do yt-dlp rodam na thread de download; a UI é tocada
    exclusivamente via GLib.idle_add — nunca travando o main loop do GTK.
  - Pausar  = aborta o download atual mantendo os arquivos .part
              (retomar depois continua de onde parou, `continuedl=True`).
  - Resiliência: cadeia de variantes (sites.py) em caso de erro.
"""

from __future__ import annotations

import logging
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# yt-dlp embutido + plugins de correção
#
# Preferimos a versão empacotada com o app (bin/yt-dlp, zipapp oficial) para
# não depender da versão do sistema, que pode estar desatualizada — é o caso
# do extrator do Rule34Video (corrigido por yt_dlp_plugins/).
# ---------------------------------------------------------------------------
_RAIZ_APP = Path(__file__).resolve().parent.parent

# zipimport só é garantido com sufixo .zip/.pyz; o binário oficial não tem.
_VENDOR_CANDIDATOS = (
    _RAIZ_APP / "bin" / "yt-dlp.zip",
    _RAIZ_APP / "bin" / "yt-dlp.pyz",
    _RAIZ_APP / "bin" / "yt-dlp",
)
for _vendor in _VENDOR_CANDIDATOS:
    if _vendor.is_file():
        sys.path.insert(0, str(_vendor))
        break
if str(_RAIZ_APP) not in sys.path:
    sys.path.insert(0, str(_RAIZ_APP))  # expõe yt_dlp_plugins ao yt-dlp

try:
    import yt_dlp
except ImportError as erro:  # sem zipapp e sem pacote instalado
    raise SystemExit(
        "yt-dlp não encontrado. Instale com: pip install yt-dlp"
    ) from erro

from .models import DownloadItem, DownloadState, FormatPreset, FORMATOS_POR_CHAVE
from .settings import Configuracoes
from . import sites

log = logging.getLogger("ytdlgtk.engine")


class DownloadAbortado(Exception):
    """Lançada dentro do progress-hook para abortar o download atual."""

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


# ---------------------------------------------------------------------------
# Logger silencioso para o yt-dlp (evita poluir o stdout do app)
# ---------------------------------------------------------------------------
class _LoggerYtdlp:
    def __init__(self, prefixo: str) -> None:
        self._p = prefixo

    def debug(self, msg):  # noqa: D102
        if str(msg).startswith("[debug]"):
            return
        log.debug("%s %s", self._p, msg)

    def info(self, msg):  # noqa: D102
        log.info("%s %s", self._p, msg)

    def warning(self, msg):  # noqa: D102
        log.warning("%s %s", self._p, msg)

    def error(self, msg):  # noqa: D102
        log.error("%s %s", self._p, msg)


# ---------------------------------------------------------------------------
# Motor
# ---------------------------------------------------------------------------
class MotorDownloads:
    """Fila concorrente thread-safe. A UI apenas chama os métodos públicos."""

    def __init__(
        self,
        config: Configuracoes,
        ao_atualizar: Callable[[DownloadItem], None],
        ao_finalizar: Callable[[DownloadItem], None],
    ) -> None:
        self._config = config
        # Callbacks já devem ser thread-safe (a UI agenda via GLib.idle_add)
        self._ao_atualizar = ao_atualizar
        self._ao_finalizar = ao_finalizar

        self._lock = threading.RLock()
        self._itens: dict[str, DownloadItem] = {}
        self._ordem: list[str] = []
        self._rodando: set[str] = set()

        self._iniciado = False
        self._fechado = False

        self._probe_pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="probe"
        )

    # ------------------------------------------------------------------
    # API pública (chamadas da UI)
    # ------------------------------------------------------------------
    def adicionar(
        self, url: str, formato: FormatPreset, altura: Optional[int] = None
    ) -> DownloadItem:
        url = (url or "").strip()
        item = DownloadItem(url=url, formato=formato, altura=altura)
        with self._lock:
            self._itens[item.id] = item
            self._ordem.append(item.id)
        self._emitir(item, forcar=True)
        self._probe_pool.submit(self._obter_metadados, item.id)
        if self._iniciado and not self._fechado:
            self._despachar()
        return item

    def iniciar_tudo(self) -> None:
        """Botão Iniciar: (re)ativa a fila e volta itens pausados para a fila."""
        with self._lock:
            if self._fechado:
                return
            self._iniciado = True
            mudou = False
            for item in list(self._itens.values()):
                if item.estado == DownloadState.PAUSADO and not item.abortar.is_set():
                    item.estado = DownloadState.AGUARDANDO
                    mudou = True
                    self._emitir(item, forcar=True)
            if mudou:
                pass  # emitido acima
        self._despachar()

    def pausar(self, item: DownloadItem) -> bool:
        """Pausa. Retorna False se o estado atual não permite (ex.: processando)."""
        with self._lock:
            if item.estado in (DownloadState.CONCLUIDO, DownloadState.ERRO, DownloadState.CANCELADO):
                return False
            if item.estado == DownloadState.PROCESSANDO:
                return False
            if item.estado == DownloadState.BAIXANDO:
                item.motivo_abort = "pausar"
                item.abortar.set()
                return True
            # aguardando/probe → pausa direta
            item.estado = DownloadState.PAUSADO
        self._emitir(item, forcar=True)
        return True

    def retomar(self, item: DownloadItem) -> None:
        with self._lock:
            if item.estado != DownloadState.PAUSADO:
                return
            item.abortar.clear()
            item.motivo_abort = ""
            item.estado = DownloadState.AGUARDANDO
        self._emitir(item, forcar=True)
        self._despachar()

    def cancelar(self, item: DownloadItem) -> None:
        with self._lock:
            if item.estado == DownloadState.BAIXANDO:
                item.motivo_abort = "cancelar"
                item.abortar.set()
                return
            item.estado = DownloadState.CANCELADO
            item.erro = ""
        self._emitir(item, forcar=True)

    def repetir(self, item: DownloadItem) -> None:
        """Tenta novamente após erro/cancelamento."""
        with self._lock:
            if item.estado == DownloadState.BAIXANDO:
                return
            item.resetar_para_retry()
        self._emitir(item, forcar=True)
        self._despachar()

    def pausar_tudo(self) -> None:
        with self._lock:
            alvo = [
                i
                for i in self._itens.values()
                if i.estado in (DownloadState.AGUARDANDO, DownloadState.BAIXANDO)
            ]
        for item in alvo:
            self.pausar(item)

    def limpar_concluidos(self) -> list[str]:
        """Remove itens concluídos/cancelados da fila. Retorna ids removidos."""
        with self._lock:
            ids = [
                i.id
                for i in self._itens.values()
                if i.estado in (DownloadState.CONCLUIDO, DownloadState.CANCELADO)
            ]
            for i in ids:
                self._itens.pop(i, None)
                if i in self._ordem:
                    self._ordem.remove(i)
        return ids

    def itens(self) -> list[DownloadItem]:
        with self._lock:
            return [self._itens[i] for i in self._ordem if i in self._itens]

    def encerrar(self) -> None:
        """No fechamento da janela: aborta tudo e solta as threads."""
        with self._lock:
            self._fechado = True
            self._iniciado = False
            for item in list(self._itens.values()):
                if not item.abortar.is_set():
                    item.abortar.set()
        self._probe_pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------
    # Despacho da fila (thread principal ou worker ao finalizar job)
    # ------------------------------------------------------------------
    def _despachar(self) -> None:
        with self._lock:
            if not self._iniciado or self._fechado:
                return
            limite = max(1, self._config.simultaneos)
            while len(self._rodando) < limite:
                item = next(
                    (
                        self._itens[i]
                        for i in self._ordem
                        if i in self._itens
                        and self._itens[i].estado == DownloadState.AGUARDANDO
                        and not self._itens[i].abortar.is_set()
                    ),
                    None,
                )
                if item is None:
                    break
                item.estado = DownloadState.BAIXANDO
                item.erro = ""
                item.info_tentativa = ""
                self._rodando.add(item.id)
                threading.Thread(
                    target=self._executar_job,
                    args=(item,),
                    name=f"dl-{item.id}",
                    daemon=True,
                ).start()
                self._emitir(item, forcar=True)

    # ------------------------------------------------------------------
    # Metadados em background (título, uploader, duração)
    # ------------------------------------------------------------------
    def _obter_metadados(self, item_id: str) -> None:
        with self._lock:
            item = self._itens.get(item_id)
            if item is None:
                return
            item.em_probe = True
            opts = self._opcoes_base(item, sites.variante_padrao(), probe=True)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(item.url, download=False)
            if info:
                with self._lock:
                    item.titulo = info.get("title") or item.titulo
                    item.uploader = info.get("uploader") or info.get("channel") or ""
                    item.duracao = info.get("duration")
                    item.playlist = bool(info.get("_type") == "playlist")
                    item.em_probe = False
                self._emitir(item, forcar=True)
        except Exception as e:
            with self._lock:
                item.em_probe = False
            log.debug("probe falhou (%s): %s", item.id, e)
            self._emitir(item, forcar=True)

    # ------------------------------------------------------------------
    # Job de download (thread própria)
    # ------------------------------------------------------------------
    def _executar_job(self, item: DownloadItem) -> None:
        try:
            self._rodar_com_variaveis(item)
        except DownloadAbortado as e:
            with self._lock:
                if e.motivo == "pausar":
                    item.estado = DownloadState.PAUSADO
                    item.velocidade = None
                    item.eta = None
                    item.info_tentativa = ""
                else:
                    item.estado = DownloadState.CANCELADO
                    self._limpar_partials(item)
            self._emitir(item, forcar=True)
        except Exception as e:  # última linha de defesa
            with self._lock:
                item.estado = DownloadState.ERRO
                item.erro = str(e) or e.__class__.__name__
                item.velocidade = None
                item.eta = None
            self._emitir(item, forcar=True)
        finally:
            with self._lock:
                self._rodando.discard(item.id)
            self._ao_finalizar_thread_safe(item)
            self._despachar()

    def _ao_finalizar_thread_safe(self, item: DownloadItem) -> None:
        try:
            self._ao_finalizar(item)
        except Exception:
            log.exception("callback ao_finalizar falhou")

    def _rodar_com_variaveis(self, item: DownloadItem) -> None:
        """Loop da cadeia de variantes (sites.py)."""
        variante = sites.variante_padrao()
        ultimo_erro = ""

        while True:
            if item.abortar.is_set():
                raise DownloadAbortado(item.motivo_abort or "cancelar")

            with self._lock:
                item.tentativa += 1
                item.info_tentativa = "" if variante.nome == "padrão" else variante.nome
            self._emitir(item, forcar=True)

            opts = self._opcoes_base(item, variante, probe=False)
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(item.url, download=True)
                    if info is None:
                        raise yt_dlp.utils.DownloadError("Nenhuma informação extraída da URL.")
                    caminho = self._resolver_caminho(ydl, info, item)
                # sucesso
                with self._lock:
                    item.estado = DownloadState.CONCLUIDO
                    item.progresso = 1.0
                    item.velocidade = None
                    item.eta = None
                    item.erro = ""
                    item.info_tentativa = ""
                    if caminho:
                        item.caminho_arquivo = caminho
                    if info.get("title"):
                        item.titulo = info["title"]
                self._emitir(item, forcar=True)
                return

            except DownloadAbortado:
                raise

            except Exception as e:
                ultimo_erro = self._mensagem_erro(e)
                log.warning(
                    "tentativa %s (%s) falhou para %s: %s",
                    item.tentativa, variante.nome, item.host or item.id, ultimo_erro,
                )
                proxima = sites.proxima_variante(ultimo_erro, variante)
                if proxima is None:
                    with self._lock:
                        item.estado = DownloadState.ERRO
                        item.erro = ultimo_erro
                        item.info_tentativa = ""
                        item.velocidade = None
                        item.eta = None
                    self._emitir(item, forcar=True)
                    return
                variante = proxima
                time.sleep(1.2)  # respiro entre tentativas

    @staticmethod
    def _mensagem_erro(e: Exception) -> str:
        if isinstance(e, yt_dlp.utils.DownloadError):
            msg = str(e)
            # remove prefixos verbosos comuns
            for pref in ("ERROR: ", "[download] ", "[generic] "):
                if msg.startswith(pref):
                    msg = msg[len(pref):]
            return msg[:300]
        return f"{e.__class__.__name__}: {e}"[:300]

    # ------------------------------------------------------------------
    # Limpeza de arquivos .part ao cancelar
    # ------------------------------------------------------------------
    def _limpar_partials(self, item: DownloadItem) -> None:
        try:
            if item.caminho_temp and os.path.exists(item.caminho_temp):
                os.remove(item.caminho_temp)
                # fragmentos residuais (.part-FragN)
                import glob

                for frag in glob.glob(item.caminho_temp + "-Frag*"):
                    try:
                        os.remove(frag)
                    except OSError:
                        pass
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Construção das opções do yt-dlp
    # ------------------------------------------------------------------
    def _opcoes_base(
        self,
        item: DownloadItem,
        variante: sites.Variante,
        probe: bool,
    ) -> dict:
        cfg = self._config
        pasta = cfg.pasta_videos_efetiva() or os.path.expanduser("~/Downloads")
        pasta = os.path.expanduser(pasta)
        try:
            os.makedirs(pasta, exist_ok=True)
        except OSError:
            pasta = os.path.expanduser("~/Downloads")

        preset: FormatPreset = item.formato or FORMATOS_POR_CHAVE["mp4"]
        site = sites.ajustes_para_url(item.url)
        origem = sites.origem_da_url(item.url)

        headers = {
            "User-Agent": sites._ua(item.id, sites._UA_MOBILE if variante.mobile else sites._UA_PADRAO),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        # Sites conhecidos: Referer/Origin desde a primeira tentativa
        if site and site.referer:
            headers["Referer"] = site.referer
            headers["Origin"] = site.referer.rstrip("/")
        if variante.endurecido:
            # Endurecido: endossos completos de navegador + fallback de referer
            headers.setdefault("Referer", origem)
            headers.setdefault("Origin", origem)
            headers.update(
                {
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "same-origin",
                    "Upgrade-Insecure-Requests": "1",
                }
            )
        if site:
            for k, v in site.headers_extra:
                headers[k] = v

        opts: dict = {
            # Caminho relativo + paths.home evita o warning "--paths is ignored"
            "outtmpl": "%(title).150B [%(id)s].%(ext)s",
            "paths": {"home": pasta},
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": _LoggerYtdlp(f"[{item.id}]"),
            "noplaylist": not cfg.permitir_playlists,
            "windowsfilenames": True,
            "continuedl": True,       # retomada de .part (essencial p/ pausar)
            "overwrites": False,
            "retries": 10,
            "fragment_retries": 10,
            "extractor_retries": 5,
            "file_access_retries": 3,
            "socket_timeout": 30,
            "geo_bypass": True,
            "concurrent_fragment_downloads": 4,
            "http_headers": headers,
            "nocheckcertificate": bool(
                cfg.ignorar_ssl or variante.sem_ssl or (site and site.insecure)
            ),
        }

        # Cookies do navegador (login / restrição de idade)
        cookies = cfg.cookies_from_browser()
        if cookies:
            opts["cookiesfrombrowser"] = cookies

        # Impersonação TLS (resolve Cloudflare em vários sites) — só se disponível
        if cfg.impersonar and self._impersonacao_disponivel():
            opts["impersonate"] = "chrome"

        if cfg.proxy and cfg.proxy.strip():
            opts["proxy"] = cfg.proxy.strip()

        if variante.generico:
            opts["force_generic_extractor"] = True

        if probe:
            opts["skip_download"] = True
            opts.pop("progress_hooks", None)
            opts.pop("postprocessor_hooks", None)
            opts.pop("postprocessors", None)
            opts.pop("merge_output_format", None)
            return opts

        # Formato / pós-processamento
        opts["format"] = preset.seletor_para(getattr(item, "altura", None))
        if preset.audio:
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                },
                {"key": "FFmpegMetadata", "add_metadata": True},
            ]
        else:
            opts["merge_output_format"] = preset.merge_ext or "mp4"

        # Hooks (rodam na thread de download; UI via idle_add)
        opts["progress_hooks"] = [lambda d: self._hook_progresso(item, d)]
        opts["postprocessor_hooks"] = [lambda d: self._hook_posproc(item, d)]

        # Extras opcionais
        if cfg.baixar_legendas and not preset.audio:
            opts.update(
                {
                    "writesubtitles": True,
                    "writeautomaticsub": True,
                    "subtitleslangs": ["pt.*", "pt", "en"],
                    "convertsubtitles": "srt",
                }
            )
        if cfg.baixar_capa:
            opts.update({"writethumbnail": True, "convertthumbnails": "jpg"})
        return opts

    _imperson_ok: Optional[bool] = None

    @classmethod
    def _impersonacao_disponivel(cls) -> bool:
        if cls._imperson_ok is None:
            try:
                import importlib.util

                cls._imperson_ok = importlib.util.find_spec("curl_cffi") is not None
            except Exception:
                cls._imperson_ok = False
        return cls._imperson_ok

    # ------------------------------------------------------------------
    # Hooks de progresso (thread do yt-dlp)
    # ------------------------------------------------------------------
    def _hook_progresso(self, item: DownloadItem, d: dict) -> None:
        if item.abortar.is_set():
            raise DownloadAbortado(item.motivo_abort or "cancelar")

        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            baixado = d.get("downloaded_bytes") or 0
            with self._lock:
                item.total = total or item.total
                item.baixado = baixado
                item.progresso = (baixado / total) if total else 0.0
                item.velocidade = d.get("speed")
                item.eta = d.get("eta")
                item.caminho_temp = d.get("tmpfilename") or item.caminho_temp
                if d.get("info_dict", {}).get("title"):
                    item.titulo = d["info_dict"]["title"]
            self._emitir(item)
        elif status == "finished":
            with self._lock:
                item.progresso = 1.0
                item.baixado = item.total or item.baixado
                item.velocidade = None
                item.eta = None
                if d.get("filename"):
                    item.caminho_arquivo = d["filename"]
                # Pós-processamento (merge/extrair áudio) vem a seguir
                item.estado = DownloadState.PROCESSANDO
            self._emitir(item, forcar=True)

    def _hook_posproc(self, item: DownloadItem, d: dict) -> None:
        if item.abortar.is_set() and item.motivo_abort == "cancelar":
            raise DownloadAbortado("cancelar")
        status = d.get("status")
        if status == "started":
            with self._lock:
                item.estado = DownloadState.PROCESSANDO
            self._emitir(item, forcar=True)
        elif status == "finished":
            with self._lock:
                if d.get("filename"):
                    item.caminho_arquivo = d["filename"]
                item.progresso = 1.0
            self._emitir(item, forcar=True)

    # ------------------------------------------------------------------
    # Resolução do caminho final (considera pós-processadores, playlists)
    # ------------------------------------------------------------------
    @staticmethod
    def _resolver_caminho(ydl: yt_dlp.YoutubeDL, info: dict, item: DownloadItem) -> str:
        candidatos: list[str] = []

        def coletar(d: dict) -> None:
            for req in d.get("requested_downloads") or []:
                for chave in ("filepath", "filename", "_filename"):
                    v = req.get(chave)
                    if v:
                        candidatos.append(v)
            for chave in ("filepath", "filename", "_filename"):
                v = d.get(chave)
                if v:
                    candidatos.append(v)

        coletar(info)
        for e in info.get("entries") or []:
            if isinstance(e, dict):
                coletar(e)

        for c in candidatos:
            if c and os.path.exists(c):
                return c

        # fallback: prepare_filename (troca extensão p/ mp3 quando aplicável)
        try:
            base = ydl.prepare_filename(info)
            if item.formato.audio and base:
                r, ext = os.path.splitext(base)
                mp3 = r + ".mp3"
                if os.path.exists(mp3):
                    return mp3
                return base
        except Exception:
            pass
        return candidatos[0] if candidatos else ""

    # ------------------------------------------------------------------
    # Emissão para a UI (com throttle)
    # ------------------------------------------------------------------
    def _emitir(self, item: DownloadItem, forcar: bool = False) -> None:
        agora = time.monotonic()
        if not forcar and (agora - item.ultimo_emit) < 0.25:
            return
        item.ultimo_emit = agora
        try:
            self._ao_atualizar(item)
        except Exception:
            log.exception("callback ao_atualizar falhou")
