"""Integração com o MPV.

Problema: o ytdl_hook do MPV chama o yt-dlp com opções padrão — sem Referer,
sem TLS flexível, sem cookies. Sites +18 (Rule34Video, XVideos, etc.) falham
ao reproduzir URL direto no MPV.

Solução: um *wrapper* do yt-dlp que o MPV usa como backend. O wrapper:
  - lê as configurações do app (cookies do navegador, proxy, SSL flexível);
  - aplica ajustes específicos por domínio (mesma tabela do sites.py);
  - em falha de SSL, tenta novamente com --no-check-certificate.
O MPV não percebe diferença — recebe o mesmo JSON do yt-dlp.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from . import plataforma

WRAPPER_NOME = "yt-dlp-mpv-wrapper"
HOOK_CONF = "ytdl_hook.conf"

# ---------------------------------------------------------------------------
# Template do wrapper — autossuficiente (MPV executa com Python puro)
# ---------------------------------------------------------------------------
WRAPPER_TEMPLATE = r'''#!/usr/bin/env python3
"""Wrapper yt-dlp para o ytdl_hook do MPV — adiciona resiliência p/ sites +18.

Gerado pelo Baixador de Vídeos (ytdlgtk). Regenerar sobrescreve este arquivo.
"""

import json
import os
import shutil
import subprocess
import sys
from urllib.parse import urlparse

# Config do app: cookies do navegador, proxy, SSL flexível
def _dir_config() -> str:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Roaming"
        )
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config"
        )
    return os.path.join(base, "ytdlgtk")


_CONF_PATH = os.path.join(_dir_config(), "config.json")

# yt-dlp embutido no app (sempre atualizado) + plugins de correção
_APP_ROOT = "__APP_ROOT__"
_BIN_APP = os.path.join(_APP_ROOT, "bin", "yt-dlp.exe" if os.name == "nt" else "yt-dlp")


def _ytdlp_bin() -> str:
    if os.path.isfile(_BIN_APP):
        return _BIN_APP
    return shutil.which("yt-dlp") or "yt-dlp"


def _env() -> dict:
    env = dict(os.environ)
    raizes = [_APP_ROOT] if os.path.isdir(_APP_ROOT) else []
    existente = env.get("PYTHONPATH", "")
    partes = [*raizes] + ([existente] if existente else [])
    env["PYTHONPATH"] = os.pathsep.join(partes)
    return env


# Domínios que precisam de tratamento especial (referer/TLS)
_SITES = {
    "rule34video.com": {"referer": "https://rule34video.com/", "insecure": True},
    "rule34videos.com": {"referer": "https://rule34video.com/", "insecure": True},
    "rule34.xxx": {"referer": "https://rule34.xxx/", "insecure": True},
    "spankbang.com": {"referer": "https://spankbang.com/", "insecure": False},
    "pornhub.com": {"referer": "https://www.pornhub.com/", "insecure": False},
    "xnxx.com": {"referer": "https://www.xnxx.com/", "insecure": True},
    "xvideos.com": {"referer": "https://www.xvideos.com/", "insecure": True},
    "xhamster.com": {"referer": "https://xhamster.com/", "insecure": False},
    "xhamster.desi": {"referer": "https://xhamster.com/", "insecure": False},
    "twitter.com": {"referer": "https://x.com/", "insecure": False},
    "x.com": {"referer": "https://x.com/", "insecure": False},
    "reddit.com": {"referer": "https://www.reddit.com/", "insecure": False},
    "redd.it": {"referer": "https://www.reddit.com/", "insecure": False},
}

_SSL_HINTS = ("ssl", "certificate", "tls", "handshake", "verify")


def _carregar_conf() -> dict:
    try:
        with open(_CONF_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _url_dos_args(args: list[str]) -> str:
    for a in reversed(args):
        if a.startswith(("http://", "https://")):
            return a
    return ""


def _extras_para_url(url: str) -> list[str]:
    conf = _carregar_conf()
    extra: list[str] = []

    host = urlparse(url).netloc.lower().removeprefix("www.")
    site = next(
        (v for dom, v in _SITES.items() if host == dom or host.endswith("." + dom)),
        None,
    )
    if site:
        if site.get("referer"):
            extra += ["--referer", site["referer"]]
        if site.get("insecure"):
            extra += ["--no-check-certificate"]

    # Cookies do navegador configurados no app
    navegador = (conf.get("navegador_cookies") or "").strip()
    if navegador:
        extra.append(f"--cookies-from-browser={navegador}")

    proxy = (conf.get("proxy") or "").strip()
    if proxy:
        extra += ["--proxy", proxy]

    return extra


def _rodar(args: list[str]) -> int:
    url = _url_dos_args(args)
    ytdlp = _ytdlp_bin()
    env = _env()

    # --version / --help: repassa direto (ytdl_hook faz checagem de versão)
    if "--version" in args or "--help" in args or not url:
        return subprocess.call([ytdlp, *args], env=env)

    extra = _extras_para_url(url)
    proc = subprocess.run([ytdlp, *extra, *args], capture_output=True, text=True, env=env)
    codigo = proc.returncode
    if codigo == 0:
        sys.stdout.write(proc.stdout or "")
        sys.stderr.write(proc.stderr or "")
        return 0

    # Falha de TLS → uma nova tentativa sem verificação de certificado
    if any(h in (proc.stderr or "").lower() for h in _SSL_HINTS):
        retry = subprocess.run(
            [ytdlp, "--no-check-certificate", *extra, *args],
            capture_output=True, text=True, env=env,
        )
        sys.stdout.write(retry.stdout or "")
        sys.stderr.write(retry.stderr or "")
        return retry.returncode

    # Sem retry: preserva stdout/stderr originais para o MPV
    sys.stdout.write(proc.stdout or "")
    sys.stderr.write(proc.stderr or "")
    return codigo


def main() -> int:
    args = sys.argv[1:]

    # Duplicações perigosas: se já houver --cookies-from-browser nos args do mpv,
    # evita conflito adicionando o nosso antes (yt-dlp usa o último).
    try:
        return _rodar(args)
    except FileNotFoundError:
        sys.stderr.write("wrapper: yt-dlp não encontrado no PATH\n")
        return 127


if __name__ == "__main__":
    sys.exit(main())
'''


def _dir_mpv() -> Path:
    if plataforma.WINDOWS:
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif plataforma.MACOS:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    d = base / "mpv"
    d.mkdir(parents=True, exist_ok=True)
    return d


def wrapper_path() -> Path:
    if plataforma.WINDOWS:
        return _dir_mpv() / (WRAPPER_NOME + ".bat")
    return _dir_mpv() / WRAPPER_NOME


def hook_conf_path() -> Path:
    return _dir_mpv() / "script-opts" / HOOK_CONF


def esta_instalado() -> bool:
    w = wrapper_path()
    conf = hook_conf_path()
    if plataforma.WINDOWS:
        return w.exists() and conf.exists()
    return w.exists() and os.access(w, os.X_OK) and conf.exists()


def instalar() -> bool:
    """Cria o wrapper e aponta o ytdl_hook do MPV para ele."""
    try:
        if not shutil.which("mpv"):
            return False

        wrapper = wrapper_path()
        conteudo = WRAPPER_TEMPLATE.replace("\"__APP_ROOT__\"", repr(str(plataforma.raiz_app())))
        if plataforma.WINDOWS:
            py = _dir_mpv() / (WRAPPER_NOME + ".py")
            py.write_text(conteudo, "utf-8")
            wrapper.write_text(
                f'@echo off\r\n"{sys.executable}" "{py}" %*\r\n', "utf-8"
            )
        else:
            wrapper.write_text(conteudo, "utf-8")
            os.chmod(wrapper, 0o755)

        conf_dir = hook_conf_path().parent
        conf_dir.mkdir(parents=True, exist_ok=True)
        # Preserva outras chaves se o arquivo já existir
        linhas = []
        if hook_conf_path().exists():
            linhas = [
                l
                for l in hook_conf_path().read_text("utf-8").splitlines()
                if not l.strip().startswith("ytdl_path")
            ]
        linhas.insert(0, f"ytdl_path={wrapper}")
        hook_conf_path().write_text("\n".join(linhas) + "\n", "utf-8")
        return True
    except OSError:
        return False


def remover() -> bool:
    """Remove wrapper e volta o ytdl_hook ao padrão (yt-dlp do PATH)."""
    try:
        wrapper_path().unlink(missing_ok=True)
        if plataforma.WINDOWS:
            (_dir_mpv() / (WRAPPER_NOME + ".py")).unlink(missing_ok=True)
        conf = hook_conf_path()
        if conf.exists():
            linhas = [
                l
                for l in conf.read_text("utf-8").splitlines()
                if not l.strip().startswith("ytdl_path")
            ]
            if linhas:
                conf.write_text("\n".join(linhas) + "\n", "utf-8")
            else:
                conf.unlink()
        return True
    except OSError:
        return False
