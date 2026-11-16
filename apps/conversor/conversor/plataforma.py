"""Diferenças entre Linux, Windows e macOS.

Tudo o que é específico de sistema (pastas do usuário, abrir arquivos,
processos e ferramentas externas) fica aqui, para o resto do app ficar
igual nas três plataformas.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

WINDOWS = os.name == "nt"
MACOS = sys.platform == "darwin"
LINUX = not WINDOWS and not MACOS

APP_DIR = "conversor"


# ---------------------------------------------------------------------------
# Pastas do usuário
# ---------------------------------------------------------------------------
def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))


def _localappdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))


def dir_config() -> Path:
    """Onde guardar configurações (mesmo lugar do app no Linux)."""
    if WINDOWS:
        base = _appdata()
    elif MACOS:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / APP_DIR


def dir_dados() -> Path:
    """Onde guardar dados do app (logs, temporários persistentes)."""
    if WINDOWS:
        base = _localappdata()
    elif MACOS:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / APP_DIR


def arquivo_config(nome: str = "config.json") -> Path:
    return dir_config() / nome


def raiz_app() -> Path:
    """Pasta do pacote/app (funciona rodando do código ou empacotado)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def pasta_binarios() -> list[Path]:
    """Pastas extras onde procurar ffmpeg, magick, 7z… (builds portáteis)."""
    candidatas = [
        raiz_app() / "bin",
        raiz_app() / "vendor",
        Path(sys.executable).parent / "bin",
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidatas.insert(0, Path(meipass) / "bin")
    return [p for p in candidatas if p.is_dir()]


def preparar_path() -> None:
    """Coloca as pastas de binários do app na frente do PATH."""
    extras = [str(p) for p in pasta_binarios()]
    if WINDOWS:
        # pip instala yt-dlp/gallery-dl em Scripts
        extras.append(str(Path(sys.executable).parent / "Scripts"))
    if not extras:
        return
    atual = os.environ.get("PATH", "")
    partes = extras + [p for p in atual.split(os.pathsep) if p]
    os.environ["PATH"] = os.pathsep.join(dict.fromkeys(partes))


def ferramenta(nome: str) -> str | None:
    """Caminho do binário (PATH + pastas do app)."""
    return shutil.which(nome)


# ---------------------------------------------------------------------------
# Abrir arquivos / pastas
# ---------------------------------------------------------------------------
def abrir_caminho(caminho: str) -> bool:
    """Abre um arquivo ou pasta no aplicativo padrão do sistema."""
    caminho = os.path.expanduser(caminho or "")
    if not caminho or not os.path.exists(caminho):
        return False
    try:
        if WINDOWS:
            os.startfile(caminho)  # type: ignore[attr-defined]
        elif MACOS:
            subprocess.Popen(["open", caminho])
        else:
            subprocess.Popen(
                ["xdg-open", caminho],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Processos
# ---------------------------------------------------------------------------
def opcoes_processo() -> dict:
    """Opções de Popen para rodar ferramentas externas sem console no Windows."""
    opts: dict = {}
    if WINDOWS:
        opts["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return opts


def encerrar(proc) -> None:
    """Termina um subprocesso (sem grupo de processos no Windows)."""
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Detalhes de ferramentas
# ---------------------------------------------------------------------------
def fonte_texto() -> str:
    """Fonte usada ao transformar texto em imagem/PDF."""
    if WINDOWS:
        return "Arial"
    if MACOS:
        return "Helvetica"
    return "DejaVu-Sans"


def pasta_temporaria() -> Path:
    base = os.environ.get("TMPDIR") or os.environ.get("TEMP") or os.environ.get("TMP")
    pasta = Path(base) if base else Path.home() / ".cache"
    try:
        pasta.mkdir(parents=True, exist_ok=True)
    except OSError:
        pasta = Path.home()
    return pasta
