"""Configurações persistentes do aplicativo (JSON em XDG_CONFIG_HOME/ytdlgtk)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

try:
    import gi

    gi.require_version("GLib", "2.0")
    from gi.repository import GLib

    def _pasta_downloads_padrao() -> str:
        d = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        return d or str(Path.home() / "Downloads")

except Exception:  # pragma: no cover

    def _pasta_downloads_padrao() -> str:
        return str(Path.home() / "Downloads")


def config_dir() -> Path:
    from . import plataforma

    d = plataforma.dir_config()
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_file() -> Path:
    return config_dir() / "config.json"


# Navegadores suportados (yt-dlp --cookies-from-browser / gallery-dl)
NAVEGADORES: tuple[tuple[str, str], ...] = (
    ("Nenhum (sem cookies)", ""),
    ("Firefox", "firefox"),
    ("Chrome", "chrome"),
    ("Chromium", "chromium"),
    ("Brave", "brave"),
    ("Edge", "edge"),
    ("Opera", "opera"),
    ("Vivaldi", "vivaldi"),
    ("Safari", "safari"),
)

TEMAS = (("Automático (sistema)", "auto"), ("Claro", "light"), ("Escuro", "dark"))


@dataclass
class Configuracoes:
    """Snapshot das preferências. A UI edita o objeto; o motor lê no início do job."""

    pasta_destino: str = field(default_factory=_pasta_downloads_padrao)  # legado / padrão
    pasta_videos: str = ""   # pasta específica para vídeos (vazio = pasta_destino)
    pasta_imagens: str = ""  # pasta específica para imagens (vazio = pasta_destino)
    simultaneos: int = 2  # 1..5
    formato_padrao: str = "mp4"  # chave de FormatPreset

    # Cookies do navegador (para conteúdo com login/restrição de idade)
    navegador_cookies: str = ""  # "" = desativado; ex.: "firefox"
    perfil_navegador: str = ""  # perfil opcional (ex.: "Profile 1")

    # Resiliência / rede
    ignorar_ssl: bool = False
    impersonar: bool = False  # requer curl_cffi instalado
    permitir_playlists: bool = False
    proxy: str = ""

    # MPV: wrapper resiliente para o ytdl_hook (reproduzir URLs +18 direto)
    integrar_mpv: bool = False

    # Aparência
    tema: str = "auto"
    qualidade_padrao: str = "melhor"

    # Extras de download
    baixar_legendas: bool = False  # grava legendas .srt quando o site oferece
    baixar_capa: bool = False      # salva a miniatura como imagem

    # Imagens (gallery-dl)
    formato_imagem: str = "original"  # original | jpg | png | webp
    max_largura_imagem: int = 0  # 0 = original; 1920 / 2560 / 3840
    limite_imagens: int = 0  # 0 = todas
    subpastas_site: bool = True  # separa por site dentro da pasta de destino

    def __post_init__(self) -> None:
        self.normalizar()

    def normalizar(self) -> None:
        self.simultaneos = max(1, min(5, int(self.simultaneos)))
        if not (self.pasta_videos or "").strip():
            self.pasta_videos = ""
        if not (self.pasta_imagens or "").strip():
            self.pasta_imagens = ""
        if self.formato_padrao not in ("mp4", "mkv", "mp3"):
            self.formato_padrao = "mp4"
        if self.navegador_cookies not in {c for _, c in NAVEGADORES}:
            self.navegador_cookies = ""
        if self.tema not in {"auto", "light", "dark"}:
            self.tema = "auto"
        if self.formato_imagem not in {"original", "jpg", "png", "webp"}:
            self.formato_imagem = "original"
        self.max_largura_imagem = max(0, min(7680, int(self.max_largura_imagem or 0)))
        self.limite_imagens = max(0, int(self.limite_imagens or 0))
        from .models import QUALIDADES_POR_CHAVE

        if self.qualidade_padrao not in QUALIDADES_POR_CHAVE:
            self.qualidade_padrao = "melhor"

    def cookies_from_browser(self) -> Optional[tuple]:
        """Tupla aceita por yt_dlp['cookiesfrombrowser'] ou None."""
        if not self.navegador_cookies:
            return None
        perfil = (self.perfil_navegador or "").strip()
        return (self.navegador_cookies, perfil) if perfil else (self.navegador_cookies,)

    def cookies_gallery(self) -> Optional[str]:
        """Valor de --cookies-from-browser para o gallery-dl."""
        if not self.navegador_cookies:
            return None
        perfil = (self.perfil_navegador or "").strip()
        return f"{self.navegador_cookies}:{perfil}" if perfil else self.navegador_cookies

    def pasta_videos_efetiva(self) -> str:
        return (self.pasta_videos or self.pasta_destino or _pasta_downloads_padrao()).strip()

    def pasta_imagens_efetiva(self) -> str:
        return (self.pasta_imagens or self.pasta_destino or _pasta_downloads_padrao()).strip()

    # ---- Persistência ----
    @classmethod
    def carregar(cls) -> "Configuracoes":
        try:
            dados = json.loads(config_file().read_text("utf-8"))
            validos = {k for k in asdict(cls()).keys()}
            dados = {k: v for k, v in dados.items() if k in validos}
            return cls(**dados)
        except Exception:
            return cls()

    def salvar(self) -> None:
        try:
            caminho = config_file()
            tmp = caminho.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), "utf-8")
            tmp.replace(caminho)
        except Exception:
            pass  # nunca derruba o app por causa de config


def aplicar_tema(valor: str) -> None:
    """Aplica o esquema de cores do libadwaita."""
    try:
        import gi

        gi.require_version("Adw", "1")
        from gi.repository import Adw

        esquema = {
            "auto": Adw.ColorScheme.DEFAULT,
            "light": Adw.ColorScheme.FORCE_LIGHT,
            "dark": Adw.ColorScheme.FORCE_DARK,
        }.get(valor, Adw.ColorScheme.DEFAULT)
        Adw.StyleManager.get_default().set_color_scheme(esquema)
    except Exception:
        pass
