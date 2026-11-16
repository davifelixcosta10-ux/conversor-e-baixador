"""Modelos de dados: itens de download, estados e formatos suportados."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DownloadState(Enum):
    """Estados possíveis de um item na fila."""

    AGUARDANDO = "aguardando"
    BAIXANDO = "baixando"
    PROCESSANDO = "processando"
    PAUSADO = "pausado"
    CONCLUIDO = "concluido"
    ERRO = "erro"
    CANCELADO = "cancelado"

    @property
    def terminal(self) -> bool:
        """Estado final (não volta mais)."""
        return self in (DownloadState.CONCLUIDO, DownloadState.ERRO, DownloadState.CANCELADO)

    @property
    def rotulo(self) -> str:
        """Rótulo em português para exibição."""
        return {
            DownloadState.AGUARDANDO: "Aguardando",
            DownloadState.BAIXANDO: "Baixando",
            DownloadState.PROCESSANDO: "Processando",
            DownloadState.PAUSADO: "Pausado",
            DownloadState.CONCLUIDO: "Concluído",
            DownloadState.ERRO: "Erro",
            DownloadState.CANCELADO: "Cancelado",
        }[self]


@dataclass(frozen=True)
class Qualidade:
    """Resolução máxima desejada (None = melhor disponível)."""

    chave: str
    rotulo: str
    altura: Optional[int] = None

    @property
    def rotulo_curto(self) -> str:
        return "Melhor" if self.altura is None else f"{self.altura}p"


QUALIDADES: tuple[Qualidade, ...] = (
    Qualidade("melhor", "Melhor disponível"),
    Qualidade("2160", "4K (2160p)", 2160),
    Qualidade("1440", "2K (1440p)", 1440),
    Qualidade("1080", "Full HD (1080p)", 1080),
    Qualidade("720", "HD (720p)", 720),
    Qualidade("480", "480p", 480),
    Qualidade("360", "360p", 360),
)

QUALIDADES_POR_CHAVE: dict[str, Qualidade] = {q.chave: q for q in QUALIDADES}
QUALIDADE_PADRAO = QUALIDADES[0]


def rotulo_qualidade(altura: Optional[int]) -> str:
    return "melhor" if not altura else f"até {altura}p"


@dataclass(frozen=True)
class FormatPreset:
    """Preset de formato: seletor yt-dlp + pós-processamento."""

    chave: str
    rotulo: str
    seletor: str
    merge_ext: Optional[str] = None
    audio: bool = False

    @property
    def icone(self) -> str:
        return "audio-x-generic-symbolic" if self.audio else "video-x-generic-symbolic"

    @property
    def rotulo_curto(self) -> str:
        return self.chave.upper()

    def seletor_para(self, altura: Optional[int]) -> str:
        """Seletor com limite de resolução (com fallback para não falhar)."""
        if self.audio or not altura:
            return self.seletor
        filtro = f"[height<={int(altura)}]"
        # Sempre termina com um fallback sem filtro: melhor baixar do que falhar.
        if self.chave == "mp4":
            return (
                f"bv*{filtro}[ext=mp4]+ba[ext=m4a]"
                f"/b{filtro}[ext=mp4]"
                f"/bv*{filtro}+ba"
                f"/b{filtro}"
                f"/bv*+ba/b"
            )
        return f"bv*{filtro}+ba/b{filtro}/bv*+ba/b"


FORMATOS: tuple[FormatPreset, ...] = (
    FormatPreset(
        chave="mp4",
        rotulo="Vídeo MP4",
        seletor="bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        merge_ext="mp4",
    ),
    FormatPreset(
        chave="mkv",
        rotulo="Vídeo MKV",
        seletor="bv*+ba/b",
        merge_ext="mkv",
    ),
    FormatPreset(
        chave="mp3",
        rotulo="Apenas áudio MP3",
        seletor="ba/b",
        audio=True,
    ),
)

FORMATO_PADRAO = FORMATOS[0]

# Índice por chave para lookup rápido
FORMATOS_POR_CHAVE: dict[str, FormatPreset] = {f.chave: f for f in FORMATOS}


# ---------------------------------------------------------------------------
# Item de vídeo
# ---------------------------------------------------------------------------
@dataclass
class DownloadItem:
    """Item da fila de downloads. Mutado pelo motor (thread de download)
    e lido pela UI (thread GTK). Campos simples são suficientes sob o GIL."""

    url: str
    formato: FormatPreset
    altura: Optional[int] = None  # limite de resolução (None = melhor)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    titulo: str = ""
    uploader: str = ""
    duracao: Optional[int] = None
    playlist: bool = False

    estado: DownloadState = DownloadState.AGUARDANDO
    progresso: float = 0.0
    velocidade: Optional[float] = None  # bytes/s
    eta: Optional[int] = None  # segundos
    baixado: int = 0
    total: int = 0
    erro: str = ""
    tentativa: int = 0
    info_tentativa: str = ""  # ex.: "tentando novamente (TLS alternativo)"

    caminho_arquivo: str = ""
    caminho_temp: str = ""

    # Controle de threads
    abortar: threading.Event = field(default_factory=threading.Event, repr=False)
    motivo_abort: str = ""  # "pausar" | "cancelar"
    em_probe: bool = False  # obtendo metadados em background
    ultimo_emit: float = 0.0  # throttle de atualização (monotônico)

    # ---- interface comum da fila (usada pelo widget de linha) ----
    @property
    def icone(self) -> str:
        return self.formato.icone

    @property
    def titulo_exibicao(self) -> str:
        return self.titulo if self.titulo else self.url

    @property
    def host(self) -> str:
        try:
            from urllib.parse import urlparse

            return urlparse(self.url).netloc.removeprefix("www.")
        except Exception:
            return ""

    @property
    def subtitulo(self) -> str:
        partes = [self.host]
        if self.formato:
            partes.append(self.formato.rotulo)
            if not self.formato.audio and self.altura:
                partes.append(rotulo_qualidade(self.altura))
        if self.uploader:
            partes.insert(1, self.uploader)
        return " · ".join(p for p in partes if p)

    @property
    def detalhe(self) -> str:
        if self.estado == DownloadState.BAIXANDO:
            pedacos = []
            if self.velocidade:
                pedacos.append(formatar_velocidade(self.velocidade))
            if self.eta is not None:
                pedacos.append(f"faltam {formatar_eta(self.eta)}")
            if self.total:
                pedacos.append(f"{formatar_bytes(self.baixado)} / {formatar_bytes(self.total)}")
            elif self.baixado:
                pedacos.append(formatar_bytes(self.baixado))
            return " · ".join(pedacos) or "iniciando…"
        if self.estado == DownloadState.CONCLUIDO:
            if self.total:
                return formatar_bytes(self.total)
            return "concluído"
        if self.estado == DownloadState.PROCESSANDO:
            return "finalizando arquivo…"
        if self.estado == DownloadState.PAUSADO:
            return f"{self.progresso * 100:.0f}% · pausado"
        if self.estado == DownloadState.AGUARDANDO:
            return "na fila" if not self.em_probe else "analisando link…"
        if self.estado == DownloadState.ERRO:
            return self.erro or "falhou"
        return ""

    def resetar_para_retry(self) -> None:
        """Prepara o item para nova tentativa (limpa erro, mantém título)."""
        self.estado = DownloadState.AGUARDANDO
        self.progresso = 0.0
        self.velocidade = None
        self.eta = None
        self.baixado = 0
        self.total = 0
        self.erro = ""
        self.info_tentativa = ""
        self.tentativa = 0
        self.abortar.clear()
        self.motivo_abort = ""
        self.caminho_temp = ""
        # caminho_arquivo mantido: se o arquivo já existe, o job pode detectar


# ---------------------------------------------------------------------------
# Item de imagens (gallery-dl)
# ---------------------------------------------------------------------------
@dataclass
class ImageItem:
    """Galeria/post de imagens baixado via gallery-dl."""

    url: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    titulo: str = ""

    estado: DownloadState = DownloadState.AGUARDANDO
    progresso: float = 0.0
    baixados: int = 0
    total_estimado: int = 0
    bytes_total: int = 0
    erro: str = ""
    arquivos: list[str] = field(default_factory=list)

    abortar: threading.Event = field(default_factory=threading.Event, repr=False)
    motivo_abort: str = ""
    em_probe: bool = True
    ultimo_emit: float = 0.0

    # ---- interface comum da fila ----
    @property
    def icone(self) -> str:
        return "image-x-generic-symbolic"

    @property
    def titulo_exibicao(self) -> str:
        return self.titulo or self.url

    @property
    def host(self) -> str:
        try:
            from urllib.parse import urlparse

            return urlparse(self.url).netloc.removeprefix("www.")
        except Exception:
            return ""

    @property
    def subtitulo(self) -> str:
        partes = [self.host]
        if self.total_estimado:
            partes.append(f"{self.total_estimado} imagens")
        elif self.arquivos:
            partes.append(f"{len(self.arquivos)} imagens")
        return " · ".join(p for p in partes if p)

    @property
    def detalhe(self) -> str:
        if self.estado == DownloadState.BAIXANDO:
            if self.total_estimado:
                txt = f"{self.baixados} de {self.total_estimado}"
            else:
                txt = f"{self.baixados} baixadas"
            if self.bytes_total:
                txt += f" · {formatar_bytes(self.bytes_total)}"
            return txt
        if self.estado == DownloadState.CONCLUIDO:
            n = len(self.arquivos)
            txt = f"{n} {'imagem' if n == 1 else 'imagens'}"
            if self.bytes_total:
                txt += f" · {formatar_bytes(self.bytes_total)}"
            return txt
        if self.estado == DownloadState.PROCESSANDO:
            return "convertendo imagens…"
        if self.estado == DownloadState.PAUSADO:
            return f"{self.baixados} baixadas · pausado"
        if self.estado == DownloadState.AGUARDANDO:
            return "analisando link…" if self.em_probe else "na fila"
        if self.estado == DownloadState.ERRO:
            return self.erro or "falhou"
        return ""

    @property
    def pasta(self) -> str:
        if not self.arquivos:
            return ""
        import os

        return os.path.dirname(self.arquivos[0])

    def resetar_para_retry(self) -> None:
        self.estado = DownloadState.AGUARDANDO
        self.progresso = 0.0
        self.baixados = 0
        self.bytes_total = 0
        self.erro = ""
        self.abortar.clear()
        self.motivo_abort = ""
        self.em_probe = True


# ---------------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------------
def formatar_bytes(n: Optional[float]) -> str:
    if n is None or n <= 0:
        return "0 B"
    for unidade in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            return f"{n:.0f} {unidade}" if unidade == "B" else f"{n:.1f} {unidade}"
        n /= 1024
    return f"{n:.1f} PiB"


def formatar_velocidade(n: Optional[float]) -> str:
    if not n:
        return "—"
    return f"{formatar_bytes(n)}/s"


def formatar_eta(segundos: Optional[int]) -> str:
    if segundos is None or segundos < 0:
        return "—"
    s = int(segundos)
    h, resto = divmod(s, 3600)
    m, sec = divmod(resto, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def formatar_duracao(segundos: Optional[int]) -> str:
    return formatar_eta(segundos)
