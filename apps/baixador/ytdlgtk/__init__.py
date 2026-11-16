"""
Baixador de Vídeos — vídeos, áudio e galerias de imagens para Linux.

Pacote modular:
  - models.py    → modelos de dados (itens, estados, formatos)
  - settings.py  → persistência de configurações (JSON em XDG_CONFIG_HOME)
  - sites.py     → resiliência para sites problemáticos (+18 e similares)
  - engine.py    → motor de vídeo thread-safe (yt-dlp)
  - images.py    → motor de galerias (gallery-dl)
  - row.py       → linha da fila (GTK4)
  - fila.py      → página de fila compartilhada (entrada, lista, rodapé)
  - videos_view.py / images_view.py → abas
  - settings_dialog.py → diálogo de preferências (Adw.PreferencesDialog)
  - window.py    → janela principal com abas
  - app.py       → Adw.Application + CSS
"""

APP_ID = "io.github.omarchy.YtdlGtk"
APP_NAME = "Baixador de Vid e Img"
APP_VERSION = "3.0.0"

__all__ = ["APP_ID", "APP_NAME", "APP_VERSION"]
