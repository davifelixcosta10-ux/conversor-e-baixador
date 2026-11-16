"""Utilitários de UI e validação compartilhados pelas páginas."""

from __future__ import annotations

import os
import subprocess
from urllib.parse import urlparse

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, Gio, GLib, Gtk


# ---------------------------------------------------------------------------
# Widgets auxiliares
# ---------------------------------------------------------------------------
def conteudo_botao(icone: str, texto: str, espacamento: int = 7) -> Gtk.Box:
    """Botão com ícone + rótulo (Gtk.Button só mostra um dos dois)."""
    caixa = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=espacamento)
    caixa.set_halign(Gtk.Align.CENTER)
    caixa.append(Gtk.Image.new_from_icon_name(icone))
    caixa.append(Gtk.Label(label=texto))
    return caixa


def rotulo_pasta(caminho: str) -> str:
    """Nome curto e legível para a pasta de destino."""
    caminho = (caminho or "").rstrip("/")
    if not caminho:
        return "Downloads"
    base = os.path.basename(caminho)
    casa = os.path.expanduser("~")
    if caminho == os.path.join(casa, "Downloads"):
        return "Downloads"
    if caminho.startswith(casa + os.sep):
        rel = caminho[len(casa) + 1 :]
        return rel if len(rel) <= 22 else "…/" + os.path.basename(caminho)
    return base if len(base) <= 22 else "…/" + base


def abrir_pasta(caminho: str) -> None:
    from . import plataforma

    caminho = os.path.expanduser(caminho or "~/Downloads")
    try:
        os.makedirs(caminho, exist_ok=True)
    except OSError:
        pass
    plataforma.abrir_caminho(caminho)


def escolher_pasta(janela, pasta_atual: str, ao_escolher) -> None:
    dialogo = Gtk.FileDialog(title="Pasta de destino")
    try:
        dialogo.set_initial_folder(Gio.File.new_for_path(os.path.expanduser(pasta_atual)))
    except Exception:
        pass

    def concluido(d, res):
        try:
            pasta = d.select_folder_finish(res)
        except GLib.Error:
            return
        if pasta:
            ao_escolher(pasta.get_path())

    dialogo.select_folder(janela, None, concluido)


def colar_texto(campo: Gtk.Entry) -> None:
    def cb(area, res):
        try:
            texto = area.read_text_finish(res)
        except GLib.Error:
            return
        if texto and texto.strip():
            campo.set_text(texto.strip())
            campo.set_position(-1)

    display = Gdk.Display.get_default()
    if display:
        display.get_clipboard().read_text_async(None, cb)


def campo_entrada(placeholder: str, icone: str = "web-browser-symbolic") -> Gtk.Entry:
    entrada = Gtk.Entry()
    entrada.set_placeholder_text(placeholder)
    entrada.set_hexpand(True)
    entrada.set_input_purpose(Gtk.InputPurpose.URL)
    entrada.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, icone)
    entrada.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "edit-paste-symbolic")
    entrada.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, "Colar da área de transferência")
    entrada.add_css_class("entrada-principal")

    def ao_clicar_icone(_e, pos):
        if pos == Gtk.EntryIconPosition.SECONDARY:
            colar_texto(entrada)

    entrada.connect("icon-press", ao_clicar_icone)
    return entrada


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------
def normalizar_url(texto: str) -> str | None:
    """Aceita 'youtube.com/…' e devolve 'https://youtube.com/…'."""
    texto = (texto or "").strip()
    if not texto or any(c.isspace() for c in texto):
        return None
    if "://" not in texto:
        texto = "https://" + texto
    try:
        p = urlparse(texto)
        if not p.netloc or "." not in p.netloc:
            return None
    except Exception:
        return None
    return texto


def urls_do_texto(texto: str) -> tuple[list[str], list[str]]:
    """Separa um texto colado em URLs válidas e inválidas."""
    validas: list[str] = []
    invalidas: list[str] = []
    for pedaco in (texto or "").replace("\r", "\n").split():
        if not pedaco.strip():
            continue
        url = normalizar_url(pedaco)
        if url:
            if url not in validas:
                validas.append(url)
        else:
            invalidas.append(pedaco)
    return validas, invalidas
