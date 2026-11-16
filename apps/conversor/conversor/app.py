"""Adw.Application: ciclo de vida e CSS."""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk

from . import APP_ID, APP_NAME, APP_VERSION, plataforma
from .window import JanelaPrincipal

_CSS = Path(__file__).with_name("data") / "style.css"


class Aplicativo(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )
        self.janela = None

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_a: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Ctrl>q"])

    def do_activate(self):
        self._carregar_css()
        if self.janela is None:
            self.janela = JanelaPrincipal(self, None)
            self.janela.connect("close-request", self._ao_fechar)
        self.janela.present()

    def do_open(self, arquivos, _n, _dica):
        """Abre arquivos vindos da linha de comando ou de 'Abrir com'."""
        if self.janela is None:
            self.do_activate()
        caminhos = [f.get_path() for f in arquivos if f.get_path()]
        if self.janela is not None and caminhos:
            self.janela.present()
            self.janela._receber(caminhos)

    def _ao_fechar(self, _j, *a) -> bool:
        if self.janela:
            self.janela.fechar()
            self.janela = None
        return False

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
            display, provedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


def principal() -> int:
    plataforma.preparar_path()
    app = Aplicativo()
    return app.run(sys.argv)
