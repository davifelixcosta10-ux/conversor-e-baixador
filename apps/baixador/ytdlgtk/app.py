"""Adw.Application: ciclo de vida, CSS e janela principal."""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Gio, Gdk

from . import APP_ID, APP_NAME, APP_VERSION
from .settings import Configuracoes, aplicar_tema
from . import plataforma
from .window import JanelaPrincipal

_CSS = Path(__file__).with_name("data") / "style.css"


class Aplicativo(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )
        self.config = Configuracoes.carregar()
        self.janela: JanelaPrincipal | None = None

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_a: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Ctrl>q"])

    def do_activate(self):  # noqa: N802 (API PyGObject)
        aplicar_tema(self.config.tema)
        self._carregar_css()

        if self.janela is None:
            self.janela = JanelaPrincipal(self, self.config)
            self.janela.connect("close-request", self._ao_fechar_janela)
        self.janela.present()

    def _ao_fechar_janela(self, _janela, *a) -> bool:
        if self.janela:
            self.janela.fechar()
            self.janela = None
        return False  # permite o fechamento

    def do_open(self, arquivos, _n, _dica):  # noqa: N802 (API PyGObject)
        """Links passados pela linha de comando ou arrastados no ícone do app."""
        urls = [f.get_uri() for f in arquivos if f.get_uri()]
        urls = [u for u in urls if u.startswith(("http://", "https://"))]
        if not urls:
            return
        if self.janela is None:
            self.do_activate()
        if self.janela is not None:
            self.janela.present()
            self.janela.pagina_videos.adicionar_urls(urls)

    def _carregar_css(self) -> None:
        if not _CSS.exists():
            return
        provedor = Gtk.CssProvider()
        try:
            provedor.load_from_path(str(_CSS))
        except Exception:
            return
        display = Gdk.Display.get_default()
        if display is None:
            return
        Gtk.StyleContext.add_provider_for_display(
            display,
            provedor,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )


def principal() -> int:
    plataforma.preparar_path()
    app = Aplicativo()
    return app.run(sys.argv)
