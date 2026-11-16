"""Motor de conversão: fila de arquivos + ffmpeg / ImageMagick / ferramentas de documento."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from typing import Callable, Optional

from . import plataforma

from .formats import (
    detectar,
    extensao_saida,
    preset_por_id,
    crf_para_qualidade,
    Preset,
)

# qualidade -> (fps, largura, cores/q)
GIF_QUALIDADE = {"alta": (15, 640, 256), "media": (12, 480, 128), "baixa": (10, 360, 96)}
WEBP_QUALIDADE = {"alta": (15, 720, 88), "media": (12, 640, 72), "baixa": (10, 480, 52)}
VP9_CRF = {"alta": 30, "media": 36, "baixa": 44}


class TrabalhoConversao:
    """Estado de um arquivo na fila de conversão."""

    def __init__(self, caminho: str):
        self.caminho = caminho
        self.nome = os.path.basename(caminho)
        self.info = detectar(caminho)
        self.tipo = self.info["tipo"]
        self.estado = "aguardando"  # aguardando | convertendo | concluido | erro | cancelado
        self.progresso = 0.0
        self.saida = ""
        self.erro = ""
        self.ultimo_emit = 0.0


class MotorConversao:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._trabalhos: list[TrabalhoConversao] = []
        self._ordem: list[str] = []
        self._rodando = False
        self._cancelar = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._processo: Optional[subprocess.Popen] = None
        self._ao_atualizar: Optional[Callable[[TrabalhoConversao], None]] = None
        self._ao_finalizar: Optional[Callable[[list[TrabalhoConversao]], None]] = None

    # ------------------------------------------------------------------
    # Arquivos
    # ------------------------------------------------------------------
    def adicionar(self, caminhos: list[str]) -> list[TrabalhoConversao]:
        novos: list[TrabalhoConversao] = []
        with self._lock:
            existentes = {t.caminho for t in self._trabalhos}
            for c in caminhos:
                if not c:
                    continue
                c = os.path.abspath(os.path.expanduser(c))
                if c in existentes or not os.path.isfile(c):
                    continue
                t = TrabalhoConversao(c)
                self._trabalhos.append(t)
                self._ordem.append(c)
                existentes.add(c)
                novos.append(t)
        return novos

    def remover(self, caminho: str) -> None:
        with self._lock:
            self._trabalhos = [t for t in self._trabalhos if t.caminho != caminho]
            if caminho in self._ordem:
                self._ordem.remove(caminho)

    def limpar_tudo(self) -> None:
        with self._lock:
            self._trabalhos.clear()
            self._ordem.clear()

    def trabalhos(self) -> list[TrabalhoConversao]:
        with self._lock:
            return list(self._trabalhos)

    def tipos_presentes(self) -> set[str]:
        return {t.tipo for t in self.trabalhos()}

    # ------------------------------------------------------------------
    # Conversão
    # ------------------------------------------------------------------
    def iniciar(
        self,
        preset_id: str,
        qualidade: str,
        pasta_saida: str,
        mesmo_lado: bool,
        ao_atualizar: Callable[[TrabalhoConversao], None],
        ao_finalizar: Callable[[list[TrabalhoConversao]], None],
        segundo_frame: float = 0.0,
    ) -> bool:
        with self._lock:
            if self._rodando:
                return False
            if not self._trabalhos:
                return False
            if preset_por_id(preset_id) is None:
                return False
            self._ao_atualizar = ao_atualizar
            self._ao_finalizar = ao_finalizar
            self._cancelar.clear()
            self._rodando = True
            for t in self._trabalhos:
                t.estado = "aguardando"
                t.progresso = 0.0
                t.erro = ""
                t.saida = ""
        self._thread = threading.Thread(
            target=self._rodar,
            args=(preset_id, qualidade, pasta_saida, mesmo_lado, segundo_frame),
            daemon=True,
        )
        self._thread.start()
        return True

    def cancelar(self) -> None:
        self._cancelar.set()
        proc = self._processo
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    @property
    def rodando(self) -> bool:
        return self._rodando

    # ------------------------------------------------------------------
    def _rodar(self, preset_id, qualidade, pasta_saida, mesmo_lado, segundo_frame) -> None:
        preset = preset_por_id(preset_id)
        try:
            trabalhos = self.trabalhos()
            pasta_saida = os.path.expanduser(pasta_saida)
            try:
                os.makedirs(pasta_saida, exist_ok=True)
            except OSError:
                pass

            if preset is not None and preset.grupo:
                self._converter_grupo(preset, trabalhos, pasta_saida, mesmo_lado)
            else:
                for t in trabalhos:
                    if self._cancelar.is_set():
                        t.estado = "cancelado"
                        self._emitir(t, forcar=True)
                        continue
                    if preset is not None and t.tipo not in preset.tipos:
                        t.estado = "erro"
                        t.erro = "tipo de arquivo incompatível com esta conversão"
                        self._emitir(t, forcar=True)
                        continue
                    t.estado = "convertendo"
                    self._emitir(t, forcar=True)
                    try:
                        saida = self._converter_um(
                            t, preset, qualidade, pasta_saida, mesmo_lado, segundo_frame
                        )
                        t.saida = saida
                        t.progresso = 1.0
                        t.estado = "concluido"
                    except Exception as e:
                        if self._cancelar.is_set():
                            t.estado = "cancelado"
                        else:
                            t.estado = "erro"
                            t.erro = str(e)[:200] or "falhou"
                    self._emitir(t, forcar=True)
        finally:
            self._rodando = False
            self._processo = None
            try:
                if self._ao_finalizar:
                    self._ao_finalizar(self.trabalhos())
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _pasta_destino(self, t: TrabalhoConversao, pasta_saida: str, mesmo_lado: bool) -> str:
        return os.path.dirname(t.caminho) if mesmo_lado else pasta_saida

    def _caminho_saida(
        self, t: TrabalhoConversao, preset: Preset, pasta_saida: str, mesmo_lado: bool
    ) -> str:
        ext = preset.ext or os.path.splitext(t.caminho)[1]
        stem = os.path.splitext(os.path.basename(t.caminho))[0]
        saida = os.path.join(self._pasta_destino(t, pasta_saida, mesmo_lado), stem + ext)
        return self._caminho_unico(saida, t.caminho)

    @staticmethod
    def _caminho_unico(saida: str, origem: str) -> str:
        """Evita sobrescrever o original ou um arquivo já existente."""
        base, ext = os.path.splitext(saida)
        if os.path.abspath(saida) == os.path.abspath(origem):
            saida = base + "_convertido" + ext
            base, ext = os.path.splitext(saida)
        n = 1
        while os.path.exists(saida) and os.path.abspath(saida) != os.path.abspath(origem):
            saida = f"{base} ({n}){ext}"
            n += 1
        return saida

    def _converter_um(self, t, preset, qualidade, pasta_saida, mesmo_lado, segundo_frame=0.0) -> str:
        if preset is None:
            raise RuntimeError("preset desconhecido")

        if preset.multiplo:
            pasta = self._pasta_destino(t, pasta_saida, mesmo_lado)
            return self._converter_multiplo(t, preset, qualidade, pasta)

        saida = self._caminho_saida(t, preset, pasta_saida, mesmo_lado)
        try:
            if preset.categoria == "video":
                self._converter_video(t, preset.id, qualidade, saida, segundo_frame)
            elif preset.categoria == "audio":
                self._converter_audio(t, preset.id, saida)
            elif preset.categoria == "image":
                self._converter_imagem(t, preset.id, qualidade, saida)
            elif preset.categoria == "documento":
                self._converter_documento(t, preset.id, qualidade, saida)
            else:
                raise RuntimeError("conversão desconhecida")
        except Exception:
            # não deixa arquivo pela metade na pasta de saída
            try:
                if os.path.isfile(saida) and os.path.getsize(saida) == 0:
                    os.remove(saida)
            except OSError:
                pass
            raise
        return saida

    # ------------------------------------------------------------------
    # Vídeo
    # ------------------------------------------------------------------
    def _converter_video(self, t, preset_id, qualidade, saida, segundo_frame) -> None:
        dur = t.info.get("duracao") or 0.0
        crf = crf_para_qualidade(qualidade)

        if preset_id == "video-mkv":
            cmd = ["ffmpeg", "-y", "-i", t.caminho, "-map", "0", "-c", "copy", saida]
        elif preset_id == "video-mp4":
            cmd = [
                "ffmpeg", "-y", "-i", t.caminho,
                "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                saida,
            ]
        elif preset_id == "video-compress":
            cmd = [
                "ffmpeg", "-y", "-i", t.caminho,
                "-vf",
                "scale=1280:720:force_original_aspect_ratio=decrease:flags=lanczos,"
                "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:v", "libx264", "-preset", "medium", "-crf", str(crf + 3),
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
                saida,
            ]
        elif preset_id == "video-webm":
            cmd = [
                "ffmpeg", "-y", "-i", t.caminho,
                "-c:v", "libvpx-vp9", "-crf", str(VP9_CRF.get(qualidade, 36)), "-b:v", "0",
                "-row-mt", "1",
                "-c:a", "libopus", "-b:a", "128k",
                saida,
            ]
        elif preset_id == "video-gif":
            fps, largura, cores = GIF_QUALIDADE.get(qualidade, GIF_QUALIDADE["media"])
            cmd = [
                "ffmpeg", "-y", "-i", t.caminho,
                "-vf",
                f"fps={fps},scale={largura}:-2:flags=lanczos,split[s0][s1];"
                f"[s0]palettegen=max_colors={cores}[p];"
                f"[s1][p]paletteuse=dither=bayer:bayer_scale=4",
                "-loop", "0", saida,
            ]
        elif preset_id == "video-webp":
            fps, largura, q = WEBP_QUALIDADE.get(qualidade, WEBP_QUALIDADE["media"])
            cmd = [
                "ffmpeg", "-y", "-i", t.caminho,
                "-vf", f"fps={fps},scale={largura}:-2:flags=lanczos",
                "-c:v", "libwebp_anim",
                "-q:v", str(q),
                "-compression_level", "6",
                "-loop", "0",
                "-an",
                saida,
            ]
        elif preset_id == "video-mute":
            cmd = [
                "ffmpeg", "-y", "-i", t.caminho,
                "-c:v", "copy", "-an", "-map", "0:v:0", "-movflags", "+faststart",
                saida,
            ]
        elif preset_id == "video-frame":
            segundo = float(segundo_frame or 0.0)
            if segundo <= 0 and dur > 0:
                segundo = min(1.0, dur / 2)
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{max(0.0, segundo):.3f}",
                "-i", t.caminho,
                "-frames:v", "1",
                "-q:v", "2",
                saida,
            ]
        elif preset_id == "video-mp3":
            cmd = ["ffmpeg", "-y", "-i", t.caminho, "-vn", "-c:a", "libmp3lame", "-q:a", "2", saida]
        else:
            raise RuntimeError("preset de vídeo desconhecido")

        self._rodar_ffmpeg(t, cmd, dur)

    # ------------------------------------------------------------------
    # Áudio
    # ------------------------------------------------------------------
    def _converter_audio(self, t, preset_id, saida) -> None:
        dur = t.info.get("duracao") or 0.0
        mapa = {
            "audio-mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
            "audio-m4a": ["-c:a", "aac", "-b:a", "192k"],
            "audio-flac": ["-c:a", "flac"],
            "audio-wav": ["-c:a", "pcm_s16le"],
            "audio-ogg": ["-c:a", "libvorbis", "-q:a", "4"],
            "audio-opus": ["-c:a", "libopus", "-b:a", "128k"],
        }
        opts = mapa.get(preset_id)
        if not opts:
            raise RuntimeError("preset de áudio desconhecido")
        cmd = ["ffmpeg", "-y", "-i", t.caminho, "-vn", *opts, saida]
        self._rodar_ffmpeg(t, cmd, dur)

    def _rodar_ffmpeg(self, t, cmd, dur) -> None:
        # -progress precisa vir antes do arquivo de saída
        cmd = [*cmd[:-1], "-progress", "pipe:1", "-nostats", cmd[-1]]

        erro: list[str] = []
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._processo = proc

        def ler_erro() -> None:
            assert proc.stderr is not None
            for linha in proc.stderr:
                erro.append(linha)

        thread_erro = threading.Thread(target=ler_erro, daemon=True)
        thread_erro.start()

        assert proc.stdout is not None
        for linha in proc.stdout:
            linha = linha.strip()
            if linha.startswith("out_time_us="):
                try:
                    us = int(linha.split("=", 1)[1])
                    if dur > 0:
                        t.progresso = min(0.99, (us / 1e6) / dur)
                except ValueError:
                    pass
                self._emitir(t)
            elif linha == "progress=end":
                t.progresso = 1.0
                self._emitir(t)
        proc.wait()
        thread_erro.join(timeout=2)
        self._processo = None

        if self._cancelar.is_set():
            raise RuntimeError("cancelado")
        if proc.returncode != 0:
            texto = "".join(erro).strip() or "ffmpeg falhou"
            raise RuntimeError(texto[-200:])

    # ------------------------------------------------------------------
    # Imagem
    # ------------------------------------------------------------------
    def _converter_imagem(self, t, preset_id, qualidade, saida) -> None:
        magick = shutil.which("magick")
        if not magick:
            raise RuntimeError("ImageMagick não encontrado")

        if preset_id == "img-resize":
            px = {"baixa": 1280, "media": 1920, "alta": 2560}.get(qualidade, 1920)
            cmd = [magick, t.caminho, "-auto-orient", "-resize", f"{px}x{px}>", saida]
        elif preset_id == "img-strip":
            cmd = [magick, t.caminho, "-auto-orient", "-strip", saida]
        elif preset_id == "img-jpg":
            cmd = [magick, t.caminho, "-auto-orient", "-quality", "92", saida]
        elif preset_id == "img-png":
            cmd = [magick, t.caminho, "-auto-orient", saida]
        elif preset_id == "img-webp":
            q = {"alta": 92, "media": 85, "baixa": 75}.get(qualidade, 85)
            cmd = [magick, t.caminho, "-auto-orient", "-quality", str(q), saida]
        elif preset_id == "img-avif":
            cmd = [magick, t.caminho, "-auto-orient", "-quality", "90", saida]
        elif preset_id == "img-tiff":
            cmd = [magick, t.caminho, "-auto-orient", saida]
        else:
            raise RuntimeError("preset de imagem desconhecido")

        t.progresso = 0.35
        self._emitir(t)
        self._executar(cmd, timeout=300)
        t.progresso = 1.0

    # ------------------------------------------------------------------
    # Documentos
    # ------------------------------------------------------------------
    def _converter_documento(self, t, preset_id, qualidade, saida) -> None:
        if preset_id in ("doc-pdf-png", "doc-pdf-jpg", "doc-pdf-txt", "doc-pdf-compress"):
            if preset_id == "doc-pdf-png":
                cmd = ["pdftoppm", "-png", "-r", "150", t.caminho, saida[:-4]]
            elif preset_id == "doc-pdf-jpg":
                cmd = ["pdftoppm", "-jpeg", "-r", "150", "-jpegopt", "quality=90", t.caminho, saida[:-4]]
            elif preset_id == "doc-pdf-txt":
                cmd = ["pdftotext", "-layout", "-enc", "UTF-8", t.caminho, saida]
            else:
                cmd = [
                    "gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.5",
                    "-dPDFSETTINGS=/ebook", "-dNOPAUSE", "-dQUIET", "-dBATCH",
                    f"-sOutputFile={saida}", t.caminho,
                ]
        elif preset_id == "doc-txt-pdf":
            self._texto_para_pdf(t, saida)
            t.progresso = 1.0
            return
        elif preset_id == "doc-img-txt":
            base = os.path.splitext(saida)[0]
            cmd = ["tesseract", t.caminho, base, "-l", "eng"]
        elif preset_id in ("doc-office-pdf", "doc-office-txt"):
            soffice = shutil.which("soffice") or shutil.which("libreoffice")
            if not soffice:
                raise RuntimeError("LibreOffice não encontrado")
            alvo = "pdf" if preset_id == "doc-office-pdf" else "txt:Text"
            self._executar(
                [
                    soffice, "--headless", "--norestore",
                    "--convert-to", alvo,
                    "--outdir", os.path.dirname(saida), t.caminho,
                ],
                timeout=300,
            )
            previsto = os.path.join(
                os.path.dirname(saida),
                os.path.splitext(os.path.basename(t.caminho))[0] + os.path.splitext(saida)[1],
            )
            if os.path.abspath(previsto) != os.path.abspath(saida) and os.path.exists(previsto):
                os.replace(previsto, saida)
            t.progresso = 1.0
            return
        else:
            raise RuntimeError("preset de documento desconhecido")

        t.progresso = 0.3
        self._emitir(t)
        self._executar(cmd, timeout=900)
        t.progresso = 1.0

    def _texto_para_pdf(self, t, saida) -> None:
        """Texto puro -> PDF A4 (renderiza com ImageMagick e pagina no A4)."""
        pasta_tmp = tempfile.mkdtemp(prefix="conversor-texto-")
        try:
            png = os.path.join(pasta_tmp, "texto.png")
            self._executar(
                [
                    "magick", "-size", "1240x", "-background", "white",
                    "-fill", "black", "-font", plataforma.fonte_texto(), "-pointsize", "28",
                    f"label:@{t.caminho}", png,
                ],
                timeout=600,
            )
            t.progresso = 0.6
            self._emitir(t, forcar=True)
            self._executar(
                [
                    "magick", png, "-density", "150", "-units", "PixelsPerInch",
                    "-crop", "1240x1754", "+repage",
                    "-compress", "jpeg", saida,
                ],
                timeout=900,
            )
        finally:
            shutil.rmtree(pasta_tmp, ignore_errors=True)

    def _converter_multiplo(self, t, preset, qualidade, pasta) -> str:
        """Conversões que geram vários arquivos (um por página) ou uma pasta."""
        stem = os.path.splitext(os.path.basename(t.caminho))[0]
        base = os.path.join(pasta, self._nome_livre_base(pasta, stem))

        if preset.id in ("doc-pdf-png", "doc-pdf-jpg"):
            cmd = [
                "pdftoppm",
                "-png" if preset.id == "doc-pdf-png" else "-jpeg",
                "-r", "150",
                t.caminho, base,
            ]
        elif preset.id == "doc-pdf-split":
            cmd = ["qpdf", "--split-pages", t.caminho, base + ".pdf"]
        elif preset.id == "outros-unzip":
            try:
                os.makedirs(base, exist_ok=True)
            except OSError as e:
                raise RuntimeError(f"não consegui criar a pasta: {e}")
            sete = plataforma.ferramenta("7z")
            if sete:
                cmd = [sete, "x", "-bd", "-y", f"-o{base}", t.caminho]
            elif t.caminho.lower().endswith(".zip"):
                self._extrair_zip(t.caminho, base)
                t.progresso = 1.0
                return base
            else:
                raise RuntimeError("instale o 7-Zip para extrair este formato")
        else:
            raise RuntimeError("conversão múltipla desconhecida")

        t.progresso = 0.3
        self._emitir(t)
        self._executar(cmd, timeout=1800)
        t.progresso = 1.0
        return base if preset.id == "outros-unzip" else pasta

    @staticmethod
    def _nome_livre_base(pasta: str, stem: str) -> str:
        base = stem
        n = 1
        existentes = os.listdir(pasta)
        while any(
            nome == base or nome.startswith(base + "-") or nome.startswith(base + ".")
            for nome in existentes
        ):
            base = f"{stem} ({n})"
            n += 1
        return base

    # ------------------------------------------------------------------
    # Conversões de grupo (vários arquivos -> um resultado)
    # ------------------------------------------------------------------
    def _converter_grupo(self, preset: Preset, trabalhos, pasta_saida, mesmo_lado) -> None:
        try:
            if preset.id == "img-pdf":
                self._grupo_imagens_pdf(trabalhos, pasta_saida, mesmo_lado)
            elif preset.id == "doc-pdf-merge":
                self._grupo_pdf_juntar(trabalhos, pasta_saida, mesmo_lado)
            elif preset.id in ("outros-zip", "outros-7z"):
                self._grupo_compactar(preset, trabalhos, pasta_saida, mesmo_lado)
            else:
                raise RuntimeError("conversão em grupo desconhecida")
        except Exception as e:
            for t in trabalhos:
                if t.estado not in ("concluido", "erro"):
                    t.estado = "erro"
                    t.erro = str(e)[:200]
                self._emitir(t, forcar=True)

    def _grupo_imagens_pdf(self, trabalhos, pasta_saida, mesmo_lado) -> None:
        magick = shutil.which("magick")
        if not magick:
            raise RuntimeError("ImageMagick não encontrado")
        imagens = [t for t in trabalhos if t.tipo == "image"]
        if not imagens:
            raise RuntimeError("nenhuma imagem na fila")
        for t in trabalhos:
            if t.tipo != "image":
                t.estado = "erro"
                t.erro = "não é imagem"
                self._emitir(t, forcar=True)

        pasta = os.path.dirname(imagens[0].caminho) if mesmo_lado else pasta_saida
        stem = os.path.splitext(os.path.basename(imagens[0].caminho))[0] or "convertido"
        saida = self._caminho_unico(os.path.join(pasta, f"{stem}.pdf"), "")

        for t in imagens:
            t.estado = "convertendo"
            t.progresso = 0.4
            self._emitir(t, forcar=True)

        self._executar([magick, *[t.caminho for t in imagens], saida], timeout=900)

        for t in imagens:
            t.saida = saida
            t.estado = "concluido"
            t.progresso = 1.0
            self._emitir(t, forcar=True)

    def _grupo_pdf_juntar(self, trabalhos, pasta_saida, mesmo_lado) -> None:
        qpdf = shutil.which("qpdf")
        if not qpdf:
            raise RuntimeError("qpdf não encontrado")
        pdfs = [t for t in trabalhos if t.tipo == "pdf"]
        if len(pdfs) < 2:
            raise RuntimeError("selecione pelo menos 2 PDFs")
        for t in trabalhos:
            if t.tipo != "pdf":
                t.estado = "erro"
                t.erro = "não é PDF"
                self._emitir(t, forcar=True)

        pasta = os.path.dirname(pdfs[0].caminho) if mesmo_lado else pasta_saida
        stem = os.path.splitext(os.path.basename(pdfs[0].caminho))[0] or "documento"
        saida = self._caminho_unico(os.path.join(pasta, f"{stem} (junto).pdf"), "")

        for t in pdfs:
            t.estado = "convertendo"
            t.progresso = 0.4
            self._emitir(t, forcar=True)

        cmd = [qpdf, "--empty", "--pages", *[t.caminho for t in pdfs], "--", saida]
        self._executar(cmd, timeout=600)

        for t in pdfs:
            t.saida = saida
            t.estado = "concluido"
            t.progresso = 1.0
            self._emitir(t, forcar=True)

    def _grupo_compactar(self, preset, trabalhos, pasta_saida, mesmo_lado) -> None:
        if not trabalhos:
            raise RuntimeError("fila vazia")
        pasta = os.path.dirname(trabalhos[0].caminho) if mesmo_lado else pasta_saida
        stem = os.path.splitext(os.path.basename(trabalhos[0].caminho))[0] or "pacote"
        saida = self._caminho_unico(os.path.join(pasta, f"{stem}{preset.ext}"), "")

        for t in trabalhos:
            t.estado = "convertendo"
            t.progresso = 0.4
            self._emitir(t, forcar=True)

        if preset.id == "outros-zip":
            self._criar_zip(saida, [t.caminho for t in trabalhos])
        else:
            self._executar(
                ["7z", "a", "-bd", "-y", saida, *[t.caminho for t in trabalhos]],
                timeout=900,
            )

        for t in trabalhos:
            t.saida = saida
            t.estado = "concluido"
            t.progresso = 1.0
            self._emitir(t, forcar=True)

    # ------------------------------------------------------------------
    @staticmethod
    def _criar_zip(saida: str, arquivos: list[str]) -> None:
        """ZIP com a biblioteca padrão (sem depender do comando zip)."""
        usados: set[str] = set()
        try:
            with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
                for caminho in arquivos:
                    nome = os.path.basename(caminho)
                    base, ext = os.path.splitext(nome)
                    n = 1
                    while nome.lower() in usados:
                        nome = f"{base} ({n}){ext}"
                        n += 1
                    usados.add(nome.lower())
                    z.write(caminho, arcname=nome)
        except Exception:
            try:
                os.remove(saida)
            except OSError:
                pass
            raise

    @staticmethod
    def _extrair_zip(origem: str, destino: str) -> None:
        with zipfile.ZipFile(origem) as z:
            for info in z.infolist():
                # impede caminhos que escapam da pasta de destino
                alvo = os.path.abspath(os.path.join(destino, info.filename))
                if not alvo.startswith(os.path.abspath(destino) + os.sep):
                    continue
                z.extract(info, destino)

    def _executar(self, cmd: list[str], timeout: int = 600) -> None:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if self._cancelar.is_set():
            raise RuntimeError("cancelado")
        if r.returncode != 0:
            texto = (r.stderr or r.stdout or "comando falhou").strip()
            texto = re.sub(r"\s+", " ", texto)
            raise RuntimeError(texto[-200:])

    # ------------------------------------------------------------------
    def _emitir(self, t, forcar=False) -> None:
        agora = time.monotonic()
        if not forcar and (agora - t.ultimo_emit) < 0.25:
            return
        t.ultimo_emit = agora
        if self._ao_atualizar:
            try:
                self._ao_atualizar(t)
            except Exception:
                pass
