"""Detecção de tipo e catálogo de conversões."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

TIPOS = ("video", "audio", "image", "pdf", "texto", "documento", "arquivo", "desconhecido")

EXTENSOES_IMAGEM = {
    ".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp", ".tiff", ".tif",
    ".gif", ".heic", ".heif", ".jxl", ".ico", ".svg", ".ppm", ".pgm", ".tga",
}
EXTENSOES_TEXTO = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".log", ".srt", ".vtt", ".rtf",
    ".html", ".htm", ".xml", ".yaml", ".yml", ".tex", ".org",
}
EXTENSOES_DOCUMENTO = {".docx", ".doc", ".odt", ".ods", ".odp", ".pptx", ".xlsx", ".epub", ".mobi"}
EXTENSOES_ARQUIVO = {
    ".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".iso", ".deb", ".rpm",
}

CATEGORIAS = (
    ("video", "Vídeos", "video-x-generic-symbolic"),
    ("audio", "Áudios", "audio-x-generic-symbolic"),
    ("image", "Imagens", "image-x-generic-symbolic"),
    ("documento", "Documentos", "x-office-document-symbolic"),
    ("outros", "Outros", "package-x-generic-symbolic"),
)

CATEGORIA_POR_ID = {c[0]: c for c in CATEGORIAS}


@dataclass(frozen=True)
class Preset:
    """Um destino de conversão do catálogo."""

    id: str
    rotulo: str
    descricao: str
    categoria: str
    tipos: tuple[str, ...]
    ext: str = ""
    requer: tuple[str, ...] = ()
    grupo: bool = False      # todos os arquivos viram um único resultado
    multiplo: bool = False   # gera vários arquivos por entrada


def _p(*args, **kwargs) -> Preset:
    return Preset(*args, **kwargs)


CATALOGO: tuple[Preset, ...] = (
    # ------------------------------------------------------------------
    # Vídeo
    # ------------------------------------------------------------------
    _p("video-mp4", "MP4 (H.264)", "Compatível com qualquer aparelho; bom para TV e WhatsApp",
       "video", ("video",), ".mp4"),
    _p("video-webm", "WebM (VP9)", "Arquivo menor com boa qualidade; popular na web",
       "video", ("video",), ".webm"),
    _p("video-mkv", "MKV (remux)", "Só troca o contêiner, sem reconverter (bem rápido)",
       "video", ("video",), ".mkv"),
    _p("video-compress", "MP4 comprimido", "Reduz para 720p e baixa o bitrate: fica bem leve",
       "video", ("video",), ".mp4"),
    _p("video-gif", "GIF em loop", "12–15 fps e até 640 px: repete sozinho em qualquer player",
       "video", ("video",), ".gif"),
    _p("video-webp", "WebP animado", "Menor que GIF e com mais cores; repete em players de imagem",
       "video", ("video",), ".webp"),
    _p("video-mute", "MP4 sem áudio", "Remove a faixa de áudio mantendo a imagem",
       "video", ("video",), ".mp4"),
    _p("video-mp3", "Extrair áudio (MP3)", "Separa a trilha sonora em MP3 192 kbps",
       "video", ("video", "audio"), ".mp3"),
    _p("video-frame", "Capturar frame (PNG)", "Salva um quadro do vídeo no segundo escolhido",
       "video", ("video",), ".png"),

    # ------------------------------------------------------------------
    # Áudio
    # ------------------------------------------------------------------
    _p("audio-mp3", "MP3", "Universal, toca em tudo",
       "audio", ("audio", "video"), ".mp3"),
    _p("audio-m4a", "M4A (AAC)", "Boa qualidade com arquivo pequeno",
       "audio", ("audio", "video"), ".m4a"),
    _p("audio-flac", "FLAC", "Sem perda de qualidade (arquivo maior)",
       "audio", ("audio", "video"), ".flac"),
    _p("audio-wav", "WAV (PCM)", "Sem compressão; ideal para edição",
       "audio", ("audio", "video"), ".wav"),
    _p("audio-ogg", "OGG (Vorbis)", "Aberto e leve",
       "audio", ("audio", "video"), ".ogg"),
    _p("audio-opus", "Opus", "Melhor qualidade por bitrate",
       "audio", ("audio", "video"), ".opus"),

    # ------------------------------------------------------------------
    # Imagem
    # ------------------------------------------------------------------
    _p("img-jpg", "JPG", "Fotografia com boa compressão",
       "image", ("image",), ".jpg"),
    _p("img-png", "PNG", "Sem perda, aceita transparência",
       "image", ("image",), ".png"),
    _p("img-webp", "WebP", "Menor que JPG mantendo qualidade",
       "image", ("image",), ".webp"),
    _p("img-avif", "AVIF", "Compressão moderna, arquivos bem pequenos",
       "image", ("image",), ".avif"),
    _p("img-tiff", "TIFF", "Alta qualidade para impressão",
       "image", ("image",), ".tiff"),
    _p("img-resize", "Redimensionar", "Mantém o formato e limita o tamanho (px)",
       "image", ("image",)),
    _p("img-strip", "Otimizar / limpar metadados", "Mantém o formato e remove dados embutidos",
       "image", ("image",)),
    _p("img-pdf", "Imagens → PDF", "Junta todas as imagens num único PDF",
       "image", ("image",), ".pdf", grupo=True),

    # ------------------------------------------------------------------
    # Documento
    # ------------------------------------------------------------------
    _p("doc-pdf-png", "PDF → PNG", "Uma imagem por página (150 dpi)",
       "documento", ("pdf",), ".png", requer=("pdftoppm",), multiplo=True),
    _p("doc-pdf-jpg", "PDF → JPG", "Uma imagem por página (150 dpi)",
       "documento", ("pdf",), ".jpg", requer=("pdftoppm",), multiplo=True),
    _p("doc-pdf-txt", "PDF → texto", "Extrai o texto pesquisável do PDF",
       "documento", ("pdf",), ".txt", requer=("pdftotext",)),
    _p("doc-pdf-compress", "PDF comprimido", "Recria o PDF com imagens mais leves",
       "documento", ("pdf",), ".pdf", requer=("gs",)),
    _p("doc-pdf-split", "Dividir PDF em páginas", "Gera um PDF por página",
       "documento", ("pdf",), ".pdf", requer=("qpdf",), multiplo=True),
    _p("doc-pdf-merge", "Juntar PDFs", "Combina todos os PDFs da fila em um só",
       "documento", ("pdf",), ".pdf", requer=("qpdf",), grupo=True),
    _p("doc-img-txt", "Imagem → texto (OCR)", "Reconhece texto na imagem (inglês)",
       "documento", ("image",), ".txt", requer=("tesseract",)),
    _p("doc-txt-pdf", "Texto → PDF", "Cada trecho do texto vira uma página A4",
       "documento", ("texto",), ".pdf", requer=("magick",)),
    _p("doc-office-pdf", "Office → PDF", "DOCX, ODT, PPTX, XLSX e EPUB viram PDF",
       "documento", ("documento",), ".pdf", requer=("soffice",)),
    _p("doc-office-txt", "Office → texto", "Extrai texto de DOCX/ODT/PPTX",
       "documento", ("documento",), ".txt", requer=("soffice",)),

    # ------------------------------------------------------------------
    # Outros
    # ------------------------------------------------------------------
    _p("outros-zip", "Compactar em ZIP", "Junta os arquivos num .zip (sem pastas)",
       "outros", TIPOS, ".zip", grupo=True),
    _p("outros-7z", "Compactar em 7z", "Compressão mais forte que o ZIP",
       "outros", TIPOS, ".7z", requer=("7z",), grupo=True),
    _p("outros-unzip", "Extrair arquivos", "Descompacta ZIP, 7z, RAR, tar… numa pasta própria",
       "outros", ("arquivo",), multiplo=True),
)

PRESETS_POR_ID = {p.id: p for p in CATALOGO}


# ---------------------------------------------------------------------------
# Detecção
# ---------------------------------------------------------------------------
def detectar(caminho: str) -> dict:
    """Retorna {'tipo', 'duracao', 'largura', 'altura', 'codec'}."""
    info = {"tipo": "desconhecido", "duracao": 0.0, "largura": 0, "altura": 0, "codec": ""}
    ext = Path(caminho).suffix.lower()

    if ext in EXTENSOES_IMAGEM:
        info["tipo"] = "image"
        try:
            r = subprocess.run(
                ["magick", "identify", "-format", "%w|%h", f"{caminho}[0]"],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0:
                partes = r.stdout.strip().split("|")
                if len(partes) == 2:
                    info["largura"] = int(partes[0])
                    info["altura"] = int(partes[1])
        except Exception:
            pass
        return info

    if ext == ".pdf":
        info["tipo"] = "pdf"
        return info
    if ext in EXTENSOES_TEXTO:
        info["tipo"] = "texto"
        return info
    if ext in EXTENSOES_DOCUMENTO:
        info["tipo"] = "documento"
        return info
    if ext in EXTENSOES_ARQUIVO:
        info["tipo"] = "arquivo"
        return info

    # ffprobe para vídeo/áudio
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_streams", "-show_format",
                "-of", "json", caminho,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            d = json.loads(r.stdout)
            streams = d.get("streams") or []
            v = next((s for s in streams if s.get("codec_type") == "video"), None)
            a = next((s for s in streams if s.get("codec_type") == "audio"), None)
            dur = float((d.get("format") or {}).get("duration") or 0)
            if v:
                info["tipo"] = "video"
                info["duracao"] = dur
                info["largura"] = int(v.get("width") or 0)
                info["altura"] = int(v.get("height") or 0)
                info["codec"] = v.get("codec_name", "")
                return info
            if a:
                info["tipo"] = "audio"
                info["duracao"] = dur
                info["codec"] = a.get("codec_name", "")
                return info
    except Exception:
        pass

    return info


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------
def binario_disponivel(nome: str) -> bool:
    if nome == "soffice":
        return shutil.which("soffice") is not None or shutil.which("libreoffice") is not None
    return shutil.which(nome) is not None


def preset_disponivel(preset: Preset) -> bool:
    return all(binario_disponivel(b) for b in preset.requer)


def presets_da_categoria(categoria: str) -> list[Preset]:
    return [
        p for p in CATALOGO
        if p.categoria == categoria and preset_disponivel(p)
    ]


def categorias_com_presets() -> list[tuple[str, str, str]]:
    return [c for c in CATEGORIAS if presets_da_categoria(c[0])]


def preset_por_id(preset_id: str) -> Preset | None:
    return PRESETS_POR_ID.get(preset_id)


def extensao_saida(preset_id: str) -> str:
    preset = PRESETS_POR_ID.get(preset_id)
    return preset.ext if preset else ""


def categoria_para_tipo(tipo: str) -> str:
    return {
        "video": "video",
        "audio": "audio",
        "image": "image",
        "pdf": "documento",
        "texto": "documento",
        "documento": "documento",
        "arquivo": "outros",
    }.get(tipo, "outros")


def aceita_tipo(preset: Preset, tipo: str) -> bool:
    return tipo in preset.tipos


def crf_para_qualidade(q: str) -> int:
    return {"alta": 18, "media": 23, "baixa": 28}.get(q, 23)
