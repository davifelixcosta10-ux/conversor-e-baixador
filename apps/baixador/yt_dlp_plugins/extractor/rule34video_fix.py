"""Extrator corrigido para o Rule34Video.

O site removeu os links de download no formato que o extrator oficial do
yt-dlp espera; agora o player usa o objeto JavaScript `flashvars` (padrão KVS).
Este plugin substitui o extrator embutido — o yt-dlp dá prioridade aos
plugins com o mesmo nome da classe.

Instalado pelo Baixador de Vídeos (ytdlgtk).
"""

from __future__ import annotations

import re

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import (
    ExtractorError,
    clean_html,
    int_or_none,
    parse_duration,
    unescapeHTML,
)


def _flashvars_para_dict(webpage: str) -> dict:
    """Converte `var flashvars = { ... };` (chaves sem aspas) em dict."""
    m = re.search(r"(?s)flashvars\s*=\s*\{(.*?)\}\s*;", webpage)
    if not m:
        return {}
    corpo = m.group(1)
    dados: dict[str, str] = {}
    for chave, valor in re.findall(r"(\w+)\s*:\s*'((?:[^'\\]|\\.)*)'", corpo):
        dados[chave] = valor.replace("\\'", "'").replace("\\\\", "\\")
    return dados


class Rule34VideoIE(InfoExtractor):  # noqa: N801 (nome exigido p/ override)
    _VALID_URL = r"https?://(?:www\.)?rule34video\.com/videos?/(?P<id>\d+)"
    IE_NAME = "rule34video"

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(
            url, video_id, headers={"Referer": "https://rule34video.com/"}
        )

        fv = _flashvars_para_dict(webpage)
        if not fv:
            raise ExtractorError(
                "Não foi possível ler o player da página (flashvars ausentes).",
                expected=True,
            )

        formats = []

        # Links diretos do flashvars (360p, 480p, 720p, 1080p…)
        pares = [("video_url", "video_url_text")]
        for n in ("", "2", "3", "4", "5", "6"):
            pares.append((f"video_alt_url{n}", f"video_alt_url{n}_text"))

        for chave_url, chave_rotulo in pares:
            url_video = fv.get(chave_url)
            if not url_video or "get_file" not in url_video:
                continue
            rotulo = fv.get(chave_rotulo, "")
            altura = int_or_none(re.sub(r"[^\d]", "", rotulo))
            ext = "mp4"
            m_ext = re.search(r"\.(\w{2,4})(?:\?|$)", url_video)
            if m_ext:
                ext = m_ext.group(1).lower()
            formats.append(
                {
                    "url": url_video,
                    "ext": ext,
                    "height": altura,
                    "format_id": rotulo.lower() or None,
                    "http_headers": {"Referer": "https://rule34video.com/"},
                }
            )

        # Fallback: links <a download=true> no formato antigo (se voltarem)
        for m in re.finditer(
            r'<a[^>]+href="(?P<u>[^"]+download=true[^"]+)"[^>]*>(?P<t>[^<]+)</a>',
            webpage,
        ):
            u, t = m.group("u"), m.group("t")
            altura = int_or_none(re.sub(r"[^\d]", "", t))
            formats.append(
                {
                    "url": u,
                    "ext": "mp4",
                    "height": altura,
                    "http_headers": {"Referer": "https://rule34video.com/"},
                }
            )

        if not formats:
            raise ExtractorError("Nenhum formato de vídeo encontrado.", expected=True)

        formats.sort(key=lambda f: (f.get("height") or 0))

        titulo = unescapeHTML(fv.get("video_title") or "")
        modelos = [
            clean_html(x) for x in re.findall(r"<a[^>]+href=\"[^\"]*models/[^\"]*\"[^>]*>([^<]+)</a>", webpage)
        ]
        categorias = [
            clean_html(x)
            for x in re.findall(r"<a[^>]+href=\"[^\"]*categories/[^\"]*\"[^>]*>([^<]+)</a>", webpage)
        ]

        return {
            "id": video_id,
            "title": titulo or f"Rule34Video {video_id}",
            "formats": formats,
            "age_limit": 18,
            "duration": parse_duration(fv.get("video_duration")),
            "thumbnail": fv.get("preview_url"),
            "uploader": ", ".join(modelos) or None,
            "categories": categorias or None,
            "webpage_url": url,
        }
