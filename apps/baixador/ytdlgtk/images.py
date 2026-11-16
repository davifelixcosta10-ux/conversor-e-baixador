"""Motor de downloads de imagens/galerias (gallery-dl).

Cada link vira um item da fila. O gallery-dl roda como processo filho e a
saída é interpretada linha a linha para alimentar o progresso na UI.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import unquote, urlparse

from .models import ImageItem, DownloadState
from .settings import Configuracoes

log = logging.getLogger("ytdlgtk.images")

_EXT_IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".heic", ".bmp", ".tiff", ".jxl"}
_EXT_IGNORAR_CONVERSAO = {".gif", ".mp4", ".webm", ".webp"}


def localizar_gallery_dl() -> Optional[str]:
    """Procura o gallery-dl instalado (PATH, pipx ou variável de ambiente)."""
    candidatos = [
        os.environ.get("GALLERY_DL_BIN", ""),
        shutil.which("gallery-dl") or "",
        str(Path(sys.executable).parent / ("gallery-dl.exe" if os.name == "nt" else "gallery-dl")),
        str(Path.home() / ".local" / "bin" / "gallery-dl"),
        str(Path.home() / ".local" / "share" / "pipx" / "venvs" / "gallery-dl" / "bin" / "gallery-dl"),
    ]
    for c in candidatos:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def _titulo_da_url(url: str) -> str:
    try:
        p = urlparse(url)
        host = (p.netloc or "").removeprefix("www.")
        resto = [seg for seg in unquote(p.path).split("/") if seg]
        if resto:
            ultimo = resto[-1].replace("-", " ").replace("_", " ").strip()
            if len(ultimo) > 42:
                ultimo = ultimo[:42].rstrip() + "…"
            return f"{host} · {ultimo}" if ultimo else host
        return host or url
    except Exception:
        return url


class MotorImagens:
    """Fila de galerias com limite de downloads simultâneos."""

    def __init__(
        self,
        config: Configuracoes,
        ao_atualizar: Callable[[ImageItem], None],
        ao_finalizar: Callable[[ImageItem], None],
    ) -> None:
        self._config = config
        self._ao_atualizar = ao_atualizar
        self._ao_finalizar = ao_finalizar

        self._lock = threading.RLock()
        self._itens: dict[str, ImageItem] = {}
        self._ordem: list[str] = []
        self._rodando: set[str] = set()
        self._processos: dict[str, subprocess.Popen] = {}

        self._iniciado = False
        self._fechado = False
        self.bin = localizar_gallery_dl()

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    @property
    def disponivel(self) -> bool:
        return self.bin is not None

    def adicionar(self, url: str) -> ImageItem:
        item = ImageItem(url=(url or "").strip(), titulo=_titulo_da_url(url))
        with self._lock:
            self._itens[item.id] = item
            self._ordem.append(item.id)
        self._emitir(item, forcar=True)
        if self._iniciado and not self._fechado:
            self._despachar()
        return item

    def iniciar_tudo(self) -> None:
        with self._lock:
            if self._fechado:
                return
            self._iniciado = True
            for item in self._itens.values():
                if item.estado == DownloadState.PAUSADO:
                    item.estado = DownloadState.AGUARDANDO
                    item.em_probe = True
                    self._emitir(item, forcar=True)
        self._despachar()

    def pausar(self, item: ImageItem) -> bool:
        with self._lock:
            if item.estado in (DownloadState.CONCLUIDO, DownloadState.ERRO, DownloadState.CANCELADO):
                return False
            if item.estado == DownloadState.BAIXANDO:
                item.motivo_abort = "pausar"
                item.abortar.set()
                self._matar(item, suave=True)
                return True
            item.estado = DownloadState.PAUSADO
        self._emitir(item, forcar=True)
        return True

    def retomar(self, item: ImageItem) -> None:
        with self._lock:
            if item.estado != DownloadState.PAUSADO:
                return
            item.abortar.clear()
            item.motivo_abort = ""
            item.estado = DownloadState.AGUARDANDO
            item.em_probe = True
        self._emitir(item, forcar=True)
        self._despachar()

    def cancelar(self, item: ImageItem) -> None:
        with self._lock:
            if item.estado == DownloadState.BAIXANDO:
                item.motivo_abort = "cancelar"
                item.abortar.set()
                self._matar(item, suave=True)
                return
            item.estado = DownloadState.CANCELADO
            item.erro = ""
        self._emitir(item, forcar=True)

    def repetir(self, item: ImageItem) -> None:
        with self._lock:
            if item.estado == DownloadState.BAIXANDO:
                return
            item.resetar_para_retry()
        self._emitir(item, forcar=True)
        self._despachar()

    def pausar_tudo(self) -> None:
        with self._lock:
            alvo = [i for i in self._itens.values() if i.estado == DownloadState.BAIXANDO]
        for item in alvo:
            self.pausar(item)
        with self._lock:
            for item in self._itens.values():
                if item.estado == DownloadState.AGUARDANDO:
                    item.estado = DownloadState.PAUSADO
                    self._emitir(item, forcar=True)

    def limpar_concluidos(self) -> list[str]:
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

    def itens(self) -> list[ImageItem]:
        with self._lock:
            return [self._itens[i] for i in self._ordem if i in self._itens]

    def encerrar(self) -> None:
        with self._lock:
            self._fechado = True
            self._iniciado = False
            itens = list(self._itens.values())
        for item in itens:
            if item.estado == DownloadState.BAIXANDO:
                item.abortar.set()
                self._matar(item, suave=False)

    # ------------------------------------------------------------------
    # Despacho
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
                item.em_probe = True
                self._rodando.add(item.id)
                threading.Thread(
                    target=self._executar, args=(item,), name=f"img-{item.id}", daemon=True
                ).start()
                self._emitir(item, forcar=True)

    def _executar(self, item: ImageItem) -> None:
        try:
            if not self.bin:
                raise RuntimeError(
                    "gallery-dl não encontrado. Instale com: pipx install gallery-dl"
                )
            self._baixar(item)
        except Exception as e:  # última linha de defesa
            with self._lock:
                item.estado = DownloadState.ERRO
                item.erro = (str(e) or e.__class__.__name__)[:300]
            self._emitir(item, forcar=True)
        finally:
            with self._lock:
                self._rodando.discard(item.id)
                self._processos.pop(item.id, None)
            try:
                self._ao_finalizar(item)
            except Exception:
                log.exception("callback ao_finalizar (imagens) falhou")
            self._despachar()

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------
    def _comando(self, item: ImageItem) -> list[str]:
        cfg = self._config
        pasta = os.path.expanduser(cfg.pasta_imagens_efetiva() or "~/Downloads")
        os.makedirs(pasta, exist_ok=True)

        cmd = [self.bin or "gallery-dl", "--no-colors"]
        if cfg.subpastas_site:
            cmd += ["-d", pasta]
        else:
            cmd += ["-D", pasta]
        if cfg.limite_imagens:
            cmd += ["--range", f"1-{int(cfg.limite_imagens)}"]
        cookies = cfg.cookies_gallery()
        if cookies:
            cmd += ["--cookies-from-browser", cookies]
        if cfg.proxy.strip():
            cmd += ["--proxy", cfg.proxy.strip()]
        if cfg.ignorar_ssl:
            cmd += ["--no-check-certificate"]
        cmd += [
            "--Print",
            "prepare:__PROGRESSO__{num}/{count}",
            item.url,
        ]
        return cmd

    def _baixar(self, item: ImageItem) -> None:
        cmd = self._comando(item)
        log.info("gallery-dl %s", " ".join(cmd[1:]))

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            start_new_session=(os.name != "nt"),
        )
        with self._lock:
            self._processos[item.id] = proc

        ultimo_erro = ""
        candidatos: set[str] = set()
        inicio = time.time()

        assert proc.stdout is not None
        for linha in proc.stdout:
            linha = linha.rstrip("\n")
            if not linha:
                continue
            if linha.startswith("__PROGRESSO__"):
                numero, total = self._ler_progresso(linha[len("__PROGRESSO__") :])
                with self._lock:
                    if total:
                        item.total_estimado = max(item.total_estimado, total)
                        item.progresso = min(1.0, numero / total)
                    if numero:
                        item.baixados = max(item.baixados, numero)
                    item.em_probe = False
                self._emitir(item)
            else:
                texto = linha.strip()
                if texto.startswith("#"):
                    texto = texto.lstrip("#").strip()
                # gallery-dl imprime o caminho absoluto do arquivo por padrão
                if texto.startswith("/") and os.path.splitext(texto)[1]:
                    candidatos.add(texto)
                elif "[error]" in texto or "[warning]" in texto:
                    if "[error]" in texto:
                        ultimo_erro = texto.split("]", 1)[-1].strip() or texto
                    log.warning("gallery-dl: %s", texto)

        codigo = proc.wait()
        if item.abortar.is_set():
            with self._lock:
                item.estado = (
                    DownloadState.CANCELADO
                    if item.motivo_abort == "cancelar"
                    else DownloadState.PAUSADO
                )
                item.em_probe = False
            self._emitir(item, forcar=True)
            return

        # coleta final dos arquivos: candidatos do stdout + varredura da pasta
        pasta = os.path.expanduser(
            self._config.pasta_imagens_efetiva()
            or self._config.pasta_destino
            or "~/Downloads"
        )
        pasta_dest = pasta
        arquivos_validos = [c for c in candidatos if os.path.isfile(c)]
        # fallback: arquivos recentes na pasta de destino
        if not arquivos_validos:
            try:
                for raiz, _, nomes in os.walk(pasta_dest):
                    for nome in nomes:
                        caminho = os.path.join(raiz, nome)
                        try:
                            if os.path.getmtime(caminho) >= inicio - 2:
                                arquivos_validos.append(caminho)
                        except OSError:
                            pass
            except OSError:
                pass
        arquivos_validos = list(dict.fromkeys(arquivos_validos))

        if codigo != 0 and not arquivos_validos:
            with self._lock:
                item.estado = DownloadState.ERRO
                item.erro = ultimo_erro or f"gallery-dl terminou com código {codigo}"
                item.em_probe = False
            self._emitir(item, forcar=True)
            return

        with self._lock:
            item.arquivos = arquivos_validos
            item.bytes_total = sum(
                os.path.getsize(f) for f in arquivos_validos if os.path.isfile(f)
            )

        # pós-processamento opcional (redimensionar / trocar formato)
        if arquivos_validos and (
            self._config.formato_imagem != "original" or self._config.max_largura_imagem
        ):
            with self._lock:
                item.estado = DownloadState.PROCESSANDO
            self._emitir(item, forcar=True)
            item.arquivos = self._pos_processar(item, arquivos_validos)

        with self._lock:
            item.estado = DownloadState.CONCLUIDO
            item.progresso = 1.0
            item.erro = ""
            item.em_probe = False
            item.bytes_total = sum(
                os.path.getsize(f) for f in item.arquivos if os.path.isfile(f)
            )
        self._emitir(item, forcar=True)

    # ------------------------------------------------------------------
    @staticmethod
    def _ler_progresso(texto: str) -> tuple[int, int]:
        try:
            a, b = texto.strip().split("/", 1)
            return int(a), int(b)
        except Exception:
            return 0, 0

    def _pos_processar(self, item: ImageItem, arquivos: list[str]) -> list[str]:
        """Redimensiona e/ou converte as imagens baixadas com o ImageMagick."""
        cfg = self._config
        alvos = [
            f
            for f in arquivos
            if os.path.isfile(f) and os.path.splitext(f)[1].lower() in _EXT_IMAGEM
            and os.path.splitext(f)[1].lower() not in _EXT_IGNORAR_CONVERSAO
        ]
        if not alvos:
            return arquivos

        magick = shutil.which("magick")
        if not magick:
            return arquivos

        resultado = list(arquivos)
        try:
            if cfg.max_largura_imagem:
                lado = int(cfg.max_largura_imagem)
                self._rodar_magick([magick, "mogrify", "-resize", f"{lado}x{lado}>", *alvos])
            if cfg.formato_imagem != "original":
                ext = "jpg" if cfg.formato_imagem == "jpg" else cfg.formato_imagem
                self._rodar_magick(
                    [magick, "mogrify", "-format", ext, "-quality", "92", *alvos]
                )
                trocados = []
                for antigo in alvos:
                    novo = os.path.splitext(antigo)[0] + ("." + ext if ext != "jpeg" else ".jpg")
                    if os.path.abspath(novo) != os.path.abspath(antigo) and os.path.isfile(novo):
                        try:
                            os.remove(antigo)
                        except OSError:
                            pass
                        trocados.append(novo)
                    else:
                        trocados.append(antigo)
                resultado = [f for f in resultado if f not in alvos] + trocados
        except Exception:
            log.exception("pós-processamento de imagens falhou")
        return resultado

    @staticmethod
    def _rodar_magick(cmd: list[str]) -> None:
        # argv pode ficar grande em galerias enormes: processa em lotes
        cabecalho, arquivos = cmd[:4], cmd[4:]
        for i in range(0, len(arquivos), 100):
            subprocess.run(
                [*cabecalho, *arquivos[i : i + 100]],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=600,
                check=False,
            )

    def _matar(self, item: ImageItem, suave: bool) -> None:
        proc = self._processos.get(item.id)
        if not proc:
            return
        try:
            if suave:
                proc.terminate()
            else:
                proc.kill()
        except OSError:
            pass

    # ------------------------------------------------------------------
    def _emitir(self, item: ImageItem, forcar: bool = False) -> None:
        agora = time.monotonic()
        if not forcar and (agora - item.ultimo_emit) < 0.3:
            return
        item.ultimo_emit = agora
        try:
            self._ao_atualizar(item)
        except Exception:
            log.exception("callback ao_atualizar (imagens) falhou")
