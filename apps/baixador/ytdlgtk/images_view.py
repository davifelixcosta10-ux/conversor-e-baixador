"""Aba Imagens: galerias e posts (gallery-dl) em resolução original."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .fila import PaginaFila
from .models import DownloadState

FORMATOS_IMAGEM = (
    ("original", "Original"),
    ("jpg", "JPG"),
    ("png", "PNG"),
    ("webp", "WebP"),
)

RESOLUCOES = (
    (0, "Original"),
    (1920, "Até 1920 px"),
    (2560, "Até 2560 px"),
    (3840, "Até 3840 px"),
)

LIMITES = (
    (0, "Todas"),
    (10, "10 imagens"),
    (25, "25 imagens"),
    (50, "50 imagens"),
    (100, "100 imagens"),
)


class PaginaImagens(PaginaFila):
    def __init__(self, janela, config, motor):
        self._pasta_attr = "pasta_imagens"
        super().__init__(janela, config, motor)

    vazio_icone = "image-x-generic-symbolic"
    vazio_titulo = "Nenhuma galeria na fila"
    vazio_descricao = (
        "Cole o link de um post, álbum ou perfil.\n"
        "Instagram, X, Reddit, Pinterest, Pixiv, DeviantArt, ArtStation e muitos outros."
    )
    placeholder = "Cole o link do post, álbum ou perfil…"
    icone_entrada = "image-x-generic-symbolic"

    # ------------------------------------------------------------------
    def _montar_banner_gallery(self) -> None:
        if self.motor.disponivel:
            return
        banner = Adw.Banner(
            title="gallery-dl não encontrado — instale com: pipx install gallery-dl",
            revealed=True,
        )
        banner.set_button_label("Copiar")
        banner.connect("button-clicked", self._copiar_instalacao)
        self.prepend(banner)

    def _copiar_instalacao(self, *_a) -> None:
        from gi.repository import Gdk

        Gdk.Display.get_default().get_clipboard().set("pipx install gallery-dl")
        self.janela.toast("Comando copiado. Rode no terminal e reabra o app.")

    # ------------------------------------------------------------------
    def montar_opcoes(self, opcoes) -> None:
        self._montar_banner_gallery()

        bloco_fmt = self._bloco("Formato")
        self.seletor_formato = Gtk.DropDown(
            model=Gtk.StringList.new([rotulo for _, rotulo in FORMATOS_IMAGEM])
        )
        self.seletor_formato.set_selected(
            next(
                (i for i, (chave, _) in enumerate(FORMATOS_IMAGEM) if chave == self.config.formato_imagem),
                0,
            )
        )
        self.seletor_formato.set_tooltip_text("Original mantém o arquivo como veio do site")
        self.seletor_formato.connect("notify::selected", self._mudou_formato)
        bloco_fmt.append(self.seletor_formato)
        opcoes.append(bloco_fmt)

        bloco_res = self._bloco("Resolução")
        self.seletor_resolucao = Gtk.DropDown(
            model=Gtk.StringList.new([rotulo for _, rotulo in RESOLUCOES])
        )
        self.seletor_resolucao.set_selected(
            next(
                (i for i, (px, _) in enumerate(RESOLUCOES) if px == self.config.max_largura_imagem),
                0,
            )
        )
        self.seletor_resolucao.set_tooltip_text(
            "O site é sempre baixado em resolução máxima; aqui você limita o tamanho final"
        )
        self.seletor_resolucao.connect("notify::selected", self._mudou_resolucao)
        bloco_res.append(self.seletor_resolucao)
        opcoes.append(bloco_res)

        bloco_lim = self._bloco("Máximo")
        self.seletor_limite = Gtk.DropDown(
            model=Gtk.StringList.new([rotulo for _, rotulo in LIMITES])
        )
        self.seletor_limite.set_selected(
            next((i for i, (n, _) in enumerate(LIMITES) if n == self.config.limite_imagens), 0)
        )
        self.seletor_limite.set_tooltip_text("Quantas imagens por link")
        self.seletor_limite.connect("notify::selected", self._mudou_limite)
        bloco_lim.append(self.seletor_limite)
        opcoes.append(bloco_lim)

    @staticmethod
    def _bloco(rotulo: str) -> Gtk.Box:
        caixa = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        caixa.set_valign(Gtk.Align.CENTER)
        lbl = Gtk.Label(label=rotulo)
        lbl.add_css_class("rotulo-opcao")
        lbl.set_valign(Gtk.Align.CENTER)
        caixa.append(lbl)
        return caixa

    # ------------------------------------------------------------------
    def adicionar_urls(self, urls: list[str]) -> int:
        criados = 0
        for url in urls:
            item = self.motor.adicionar(url)
            self.registrar(item)
            criados += 1
        return criados

    def abrir_item(self, item) -> None:
        from .util import abrir_pasta

        pasta = item.pasta or self.config.pasta_imagens_efetiva()
        abrir_pasta(pasta)

    def _mensagem_sucesso(self, item) -> str:
        n = len(item.arquivos)
        return f"{n} {'imagem baixada' if n == 1 else 'imagens baixadas'}"

    # ------------------------------------------------------------------
    def _mudou_formato(self, combo, _p) -> None:
        idx = combo.get_selected()
        if 0 <= idx < len(FORMATOS_IMAGEM):
            self.config.formato_imagem = FORMATOS_IMAGEM[idx][0]
            self.config.salvar()

    def _mudou_resolucao(self, combo, _p) -> None:
        idx = combo.get_selected()
        if 0 <= idx < len(RESOLUCOES):
            self.config.max_largura_imagem = RESOLUCOES[idx][0]
            self.config.salvar()

    def _mudou_limite(self, combo, _p) -> None:
        idx = combo.get_selected()
        if 0 <= idx < len(LIMITES):
            self.config.limite_imagens = LIMITES[idx][0]
            self.config.salvar()

    def recap_preferencias(self) -> None:
        self.atualizar_destino()
