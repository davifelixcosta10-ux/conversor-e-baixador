"""Resiliência para sites problemáticos (incluindo +18).

Estratégia em camadas:
  1. Tentativa padrão com User-Agent dinâmico e retries generosos.
  2. Em 401/403/429 ou erros de login/idade → "endurecido": headers de navegador
     completos + Referer/Origin da própria URL (resgata muitos sites de CDN).
  3. Em erros TLS/SSL → sem verificação de certificado.
  4. Em extrator quebrado/URL não suportada → fallback do extrator genérico.
  5. Se curl_cffi estiver disponível, impersonação de navegador resolve Cloudflare.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Perfis de User-Agent (rotação dinâmica por item)
# ---------------------------------------------------------------------------
USER_AGENTS: tuple[str, ...] = (
    # Chrome estável Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    # Firefox Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    # Safari macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    # Chrome Android (útil para CDNs mobile-only)
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
)

# Índices estáveis para variar entre tentativas
_UA_PADRAO = 0
_UA_ALTERNATIVO = 1
_UA_MOBILE = 3


def _ua(seed: str, indice: int = _UA_PADRAO) -> str:
    """UA determinístico por seed (ex.: id do item) — evita 'multi-UA' no mesmo site."""
    if not USER_AGENTS:
        return "Mozilla/5.0"
    offset = sum(seed.encode()) % len(USER_AGENTS)
    return USER_AGENTS[(indice + offset) % len(USER_AGENTS)]


def origem_da_url(url: str) -> str:
    """Ex.: 'https://rule34video.com' — usado como Referer/Origin."""
    try:
        p = urlparse(url)
        return f"{p.scheme or 'https'}://{p.netloc}" or url
    except Exception:
        return url


# ---------------------------------------------------------------------------
# Ajustes por site conhecido (extratores que quebram com frequência)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AjustesSite:
    nome: str
    dominios: tuple[str, ...]
    referer: str = ""
    headers_extra: tuple[tuple[str, str], ...] = ()
    insecure: bool = False


_SITES: tuple[AjustesSite, ...] = (
    AjustesSite(
        nome="Rule34Video",
        dominios=("rule34video.com", "rule34videos.com"),
        referer="https://rule34video.com/",
        insecure=True,
    ),
    AjustesSite(
        nome="Rule34XXX",
        dominios=("rule34.xxx",),
        referer="https://rule34.xxx/",
        insecure=True,
    ),
    AjustesSite(
        nome="SpankBang",
        dominios=("spankbang.com",),
        referer="https://spankbang.com/",
    ),
    AjustesSite(
        nome="PornHub",
        dominios=("pornhub.com",),
        referer="https://www.pornhub.com/",
    ),
    AjustesSite(
        nome="XNXX",
        dominios=("xnxx.com",),
        referer="https://www.xnxx.com/",
        insecure=True,
    ),
    AjustesSite(
        nome="XVideos",
        dominios=("xvideos.com",),
        referer="https://www.xvideos.com/",
        insecure=True,
    ),
    AjustesSite(
        nome="XHamster",
        dominios=("xhamster.com", "xhamster.desi"),
        referer="https://xhamster.com/",
    ),
    AjustesSite(
        nome="Twitter/X",
        dominios=("twitter.com", "x.com", "t.co"),
        referer="https://x.com/",
    ),
    AjustesSite(
        nome="Reddit",
        dominios=("reddit.com", "redd.it", "v.redd.it"),
        referer="https://www.reddit.com/",
    ),
)


def ajustes_para_url(url: str) -> AjustesSite | None:
    host = (urlparse(url).netloc or "").lower().removeprefix("www.")
    for site in _SITES:
        if any(host == d or host.endswith("." + d) for d in site.dominios):
            return site
    return None


# ---------------------------------------------------------------------------
# Variantes de tentativa (cadeia de fallback)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Variante:
    """Modificadores aplicados sobre as opções-base do yt-dlp."""

    nome: str  # exibido no status: "tentando novamente (TLS alternativo)"
    endurecido: bool = False  # headers completos + Referer/Origin + UA alternativo
    sem_ssl: bool = False  # nocheckcertificate
    generico: bool = False  # force_generic_extractor
    mobile: bool = False  # UA mobile


_SSL_HINTS = ("ssl", "certificate", "certificado", "tls", "handshake", "verify")
_AUTH_HINTS = (
    "403", "401", "429", "forbidden", "unauthorized", "login", "sign in",
    "sign-in", "cookies", "cookie", "age", "idade", "restricted", "private",
    "members", "cloudflare", "captcha", "permission", "permissão",
)
_EXTRACT_HINTS = (
    "unsupported url", "no video formats", "unable to extract", "extractor",
    "failed to extract", "no suitable", "não foi possível extrair",
)


def _contem(texto: str, pistas: tuple[str, ...]) -> bool:
    t = texto.lower()
    return any(p in t for p in pistas)


def proxima_variante(erro_texto: str, usada: Variante) -> Variante | None:
    """Decide a próxima tentativa a partir do texto do erro. None = desistir."""
    if not usada.sem_ssl and _contem(erro_texto, _SSL_HINTS):
        return Variante("TLS alternativo", sem_ssl=True, endurecido=usada.endurecido)
    if not usada.endurecido and _contem(erro_texto, _AUTH_HINTS):
        return Variante("cabeçalhos de navegador", endurecido=True, sem_ssl=usada.sem_ssl)
    if not usada.endurecido and not usada.mobile and _contem(erro_texto, ("http error",)):
        return Variante("UA alternativo", endurecido=True, mobile=True, sem_ssl=usada.sem_ssl)
    if not usada.generico and _contem(erro_texto, _EXTRACT_HINTS):
        return Variante(
            "extrator genérico",
            endurecido=True,
            sem_ssl=usada.sem_ssl or True,
            generico=True,
        )
    return None


def variante_padrao() -> Variante:
    return Variante("padrão")
