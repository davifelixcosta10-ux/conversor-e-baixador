#!/usr/bin/env python3
"""Ponto de entrada do Baixador de Vídeos (yt-dlp + GTK4)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ytdlgtk.app import principal  # noqa: E402

if __name__ == "__main__":
    sys.exit(principal())
