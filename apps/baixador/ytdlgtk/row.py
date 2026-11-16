"""Linha da fila — um único widget serve vídeos e galerias de imagens."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Pango

from .models import DownloadState

# classes CSS por estado (cor do ícone + progresso)
_CLASSE_ESTADO = {
    DownloadState.AGUARDANDO: "aguardando",
    DownloadState.BAIXANDO: "baixando",
    DownloadState.PROCESSANDO: "processando",
    DownloadState.PAUSADO: "pausado",
    DownloadState.CONCLUIDO: "concluido",
    DownloadState.ERRO: "erro",
    DownloadState.CANCELADO: "cancelado",
}


class LinhaFila(Gtk.ListBoxRow):
    """Item da fila: ícone, título, meta, progresso fino e ações."""

    def __init__(self, item, ao_alternar, ao_cancelar, ao_abrir, ao_abrir_pasta=None):
        super().__init__()
        self.item = item
        self.set_activatable(False)
        self.set_selectable(False)
        self._ao_alternar = ao_alternar  # pausar / retomar / repetir
        self._ao_cancelar = ao_cancelar
        self._ao_abrir = ao_abrir
        self._ao_abrir_pasta = ao_abrir_pasta

        self._montar()
        self.atualizar()

    # ------------------------------------------------------------------
    def _montar(self) -> None:
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        caixa.set_margin_top(10)
        caixa.set_margin_bottom(10)
        caixa.set_margin_start(14)
        caixa.set_margin_end(10)
        self.set_child(caixa)

        topo = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        caixa.append(topo)

        # ícone do tipo de mídia dentro de um "chip" colorido por estado
        self.chip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.chip.add_css_class("chip-icone")
        self.chip.set_valign(Gtk.Align.CENTER)
        self.icone = Gtk.Image()
        self.icone.set_pixel_size(16)
        self.icone.set_halign(Gtk.Align.CENTER)
        self.icone.set_valign(Gtk.Align.CENTER)
        self.chip.append(self.icone)
        topo.append(self.chip)

        textos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        textos.set_hexpand(True)
        textos.set_valign(Gtk.Align.CENTER)
        topo.append(textos)

        self.rotulo_titulo = Gtk.Label()
        self.rotulo_titulo.set_halign(Gtk.Align.START)
        self.rotulo_titulo.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.rotulo_titulo.set_single_line_mode(True)
        self.rotulo_titulo.add_css_class("titulo-item")
        textos.append(self.rotulo_titulo)

        self.rotulo_meta = Gtk.Label()
        self.rotulo_meta.set_halign(Gtk.Align.START)
        self.rotulo_meta.set_ellipsize(Pango.EllipsizeMode.END)
        self.rotulo_meta.set_single_line_mode(True)
        self.rotulo_meta.add_css_class("meta-item")
        textos.append(self.rotulo_meta)

        # percentual / estado
        self.rotulo_estado = Gtk.Label()
        self.rotulo_estado.set_valign(Gtk.Align.CENTER)
        self.rotulo_estado.set_xalign(1.0)
        self.rotulo_estado.add_css_class("estado-item")
        topo.append(self.rotulo_estado)

        # ações
        acoes = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        acoes.set_valign(Gtk.Align.CENTER)
        topo.append(acoes)

        self.btn_abrir = self._botao("media-playback-start-symbolic", "Abrir", "verde")
        self.btn_abrir.connect("clicked", lambda _b: self._ao_abrir(self.item))
        acoes.append(self.btn_abrir)

        self.btn_pasta = self._botao("folder-symbolic", "Abrir a pasta", "azul")
        self.btn_pasta.connect("clicked", lambda _b: self._abrir_pasta())
        acoes.append(self.btn_pasta)

        self.btn_repetir = self._botao("view-refresh-symbolic", "Tentar de novo", "azul")
        self.btn_repetir.connect("clicked", lambda _b: self._ao_alternar(self.item))
        acoes.append(self.btn_repetir)

        self.btn_pausar = self._botao("media-playback-pause-symbolic", "Pausar", "azul")
        self.btn_pausar.connect("clicked", lambda _b: self._ao_alternar(self.item))
        acoes.append(self.btn_pausar)

        self.btn_cancelar = self._botao("window-close-symbolic", "Cancelar", "vermelho")
        self.btn_cancelar.connect("clicked", lambda _b: self._ao_cancelar(self.item))
        acoes.append(self.btn_cancelar)

        # progresso fino
        self.progresso = Gtk.ProgressBar()
        self.progresso.set_show_text(False)
        self.progresso.add_css_class("progresso-item")
        caixa.append(self.progresso)

    @staticmethod
    def _botao(icone: str, dica: str, cor: str) -> Gtk.Button:
        botao = Gtk.Button.new_from_icon_name(icone)
        botao.set_tooltip_text(dica)
        botao.add_css_class("acao-item")
        botao.add_css_class(f"acao-{cor}")
        return botao

    def _abrir_pasta(self) -> None:
        if self._ao_abrir_pasta is not None:
            self._ao_abrir_pasta(self.item)

    # ------------------------------------------------------------------
    def atualizar(self) -> None:
        item = self.item

        for cls in _CLASSE_ESTADO.values():
            self.remove_css_class(cls)
            self.chip.remove_css_class(cls)
        chave = _CLASSE_ESTADO.get(item.estado, "aguardando")
        self.add_css_class(chave)
        self.chip.add_css_class(chave)

        self.icone.set_from_icon_name(item.icone)

        self.rotulo_titulo.set_text(item.titulo_exibicao)
        self.rotulo_titulo.set_tooltip_text(item.titulo or item.url)

        meta = item.subtitulo
        detalhe = item.detalhe
        if detalhe:
            meta = f"{meta} · {detalhe}" if meta else detalhe
        self.rotulo_meta.set_text(meta)
        self.rotulo_meta.set_tooltip_text(detalhe or item.url)

        # rótulo à direita
        if item.estado == DownloadState.BAIXANDO:
            self.rotulo_estado.set_text(f"{item.progresso * 100:.0f}%")
        elif item.estado == DownloadState.CONCLUIDO:
            self.rotulo_estado.set_text("✓")
        elif item.estado == DownloadState.ERRO:
            self.rotulo_estado.set_text("!")
        elif item.estado == DownloadState.PAUSADO:
            self.rotulo_estado.set_text("pausado")
        elif item.estado == DownloadState.PROCESSANDO:
            self.rotulo_estado.set_text("…")
        elif item.estado == DownloadState.AGUARDANDO:
            self.rotulo_estado.set_text("na fila")
        else:
            self.rotulo_estado.set_text("—")

        # progresso
        if item.estado == DownloadState.PROCESSANDO or (
            item.estado == DownloadState.AGUARDANDO and getattr(item, "em_probe", False)
        ):
            self.progresso.pulse()
        else:
            self.progresso.set_fraction(max(0.0, min(1.0, item.progresso)))

        # botões visíveis conforme o estado
        pode_pausar = item.estado in (
            DownloadState.AGUARDANDO,
            DownloadState.BAIXANDO,
            DownloadState.PAUSADO,
        )
        pode_cancelar = item.estado in (
            DownloadState.AGUARDANDO,
            DownloadState.BAIXANDO,
            DownloadState.PAUSADO,
            DownloadState.PROCESSANDO,
        )
        pode_repetir = item.estado in (DownloadState.ERRO, DownloadState.CANCELADO)
        pode_abrir = item.estado == DownloadState.CONCLUIDO

        self.btn_pausar.set_visible(pode_pausar)
        self.btn_cancelar.set_visible(pode_cancelar)
        self.btn_repetir.set_visible(pode_repetir)
        self.btn_abrir.set_visible(pode_abrir)
        self.btn_pasta.set_visible(pode_abrir)

        if item.estado == DownloadState.PAUSADO:
            self.btn_pausar.set_icon_name("media-playback-start-symbolic")
            self.btn_pausar.set_tooltip_text("Retomar")
        else:
            self.btn_pausar.set_icon_name("media-playback-pause-symbolic")
            self.btn_pausar.set_tooltip_text("Pausar")

        self.btn_cancelar.set_sensitive(item.estado != DownloadState.PROCESSANDO)
