"""Página de fila reutilizável: entrada de links, lista e rodapé de controle."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, GObject, Gtk, Pango

from .models import DownloadState
from .row import LinhaFila
from .util import campo_entrada, colar_texto, conteudo_botao, rotulo_pasta, urls_do_texto


class PaginaFila(Gtk.Box):
    """Base das abas Vídeos e Imagens.

    As subclasses definem textos, o conteúdo da linha de opções e como
    adicionar URLs ao motor correspondente.
    """

    vazio_icone = "folder-download-symbolic"
    vazio_titulo = "Nada na fila"
    vazio_descricao = ""
    placeholder = "Cole um link…"
    icone_entrada = "web-browser-symbolic"
    dica = ""

    def __init__(self, janela, config, motor):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.janela = janela
        self.config = config
        self.motor = motor
        self.linhas: dict[str, LinhaFila] = {}
        if not hasattr(self, "_pasta_attr"):
            self._pasta_attr = "pasta_destino"

        self._montar_entrada()
        self._montar_fila()
        self._montar_rodape()
        self._refletir()

    # ==================================================================
    # Construção
    # ==================================================================
    def _montar_entrada(self) -> None:
        clamp = Adw.Clamp(maximum_size=880, tightening_threshold=720)
        clamp.set_vexpand(True)
        clamp.set_margin_top(12)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)
        self.append(clamp)

        corpo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        corpo.set_vexpand(True)
        clamp.set_child(corpo)

        cartao = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        cartao.add_css_class("cartao-entrada")
        corpo.append(cartao)

        linha1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        cartao.append(linha1)

        self.campo_url = campo_entrada(self.placeholder, self.icone_entrada)
        self.campo_url.connect("activate", lambda _e: self._adicionar())
        self.campo_url.connect(
            "changed",
            lambda e: self.btn_adicionar.set_sensitive(bool(e.get_text().strip())),
        )
        linha1.append(self.campo_url)

        self.btn_adicionar = Gtk.Button()
        self.btn_adicionar.add_css_class("suggested-action")
        self.btn_adicionar.add_css_class("botao-baixar")
        self.btn_adicionar.set_child(conteudo_botao("folder-download-symbolic", "Baixar"))
        self.btn_adicionar.set_tooltip_text("Adicionar à fila (Enter)")
        self.btn_adicionar.set_sensitive(False)
        self.btn_adicionar.connect("clicked", lambda _b: self._adicionar())
        linha1.append(self.btn_adicionar)

        self.opcoes = Adw.WrapBox(child_spacing=8, line_spacing=8)
        self.opcoes.set_margin_top(2)
        cartao.append(self.opcoes)

        self.btn_destino = Gtk.Button()
        self.btn_destino.add_css_class("chip")
        self.btn_destino.set_tooltip_text("Escolher pasta de destino")
        self.btn_destino.connect(
            "clicked", lambda _b: self.janela.escolher_destino(self._pasta_attr)
        )
        self.opcoes.append(self.btn_destino)
        self.atualizar_destino()

        self.montar_opcoes(self.opcoes)

        # cabeçalho da fila
        cabecalho = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        cabecalho.set_margin_top(16)
        cabecalho.set_margin_bottom(6)
        corpo.append(cabecalho)

        titulo = Gtk.Label(label="Fila", xalign=0.0)
        titulo.add_css_class("titulo-secao")
        titulo.set_hexpand(True)
        cabecalho.append(titulo)

        self.rotulo_contador = Gtk.Label()
        self.rotulo_contador.add_css_class("contador")
        self.rotulo_contador.set_valign(Gtk.Align.CENTER)
        cabecalho.append(self.rotulo_contador)

    def _montar_fila(self) -> None:
        self.pilha = Gtk.Stack()
        self.pilha.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.pilha.set_vexpand(True)
        self.append(self.pilha)

        self.lista = Gtk.ListBox()
        self.lista.set_selection_mode(Gtk.SelectionMode.NONE)
        self.lista.add_css_class("boxed-list")
        self.lista.add_css_class("fila")
        self.lista.set_valign(Gtk.Align.START)

        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            propagate_natural_height=True,
        )
        scroll.set_child(self.lista)
        scroll.set_vexpand(True)
        self.pilha.add_named(scroll, "fila")

        vazio = Adw.StatusPage(
            icon_name=self.vazio_icone,
            title=self.vazio_titulo,
            description=self.vazio_descricao,
        )
        vazio.add_css_class("estado-vazio")
        vazio.set_vexpand(True)
        self.pilha.add_named(vazio, "vazio")

        self.pilha.set_visible_child_name("vazio")

    def _montar_rodape(self) -> None:
        rodape = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        rodape.add_css_class("rodape")
        rodape.set_margin_start(16)
        rodape.set_margin_end(16)
        rodape.set_margin_top(8)
        rodape.set_margin_bottom(8)
        self.append(rodape)

        self.rotulo_resumo = Gtk.Label(xalign=0.0)
        self.rotulo_resumo.add_css_class("resumo")
        self.rotulo_resumo.set_hexpand(True)
        self.rotulo_resumo.set_ellipsize(Pango.EllipsizeMode.END)
        self.rotulo_resumo.set_valign(Gtk.Align.CENTER)
        rodape.append(self.rotulo_resumo)

        self.btn_retomar_tudo = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        self.btn_retomar_tudo.set_tooltip_text("Retomar / iniciar a fila")
        self.btn_retomar_tudo.add_css_class("acao-rodape")
        self.btn_retomar_tudo.connect("clicked", lambda _b: self.motor.iniciar_tudo())
        rodape.append(self.btn_retomar_tudo)

        self.btn_pausar_tudo = Gtk.Button.new_from_icon_name("media-playback-pause-symbolic")
        self.btn_pausar_tudo.set_tooltip_text("Pausar tudo")
        self.btn_pausar_tudo.add_css_class("acao-rodape")
        self.btn_pausar_tudo.connect("clicked", lambda _b: self.motor.pausar_tudo())
        rodape.append(self.btn_pausar_tudo)

        self.btn_limpar = Gtk.Button.new_from_icon_name("edit-clear-all-symbolic")
        self.btn_limpar.set_tooltip_text("Limpar itens concluídos")
        self.btn_limpar.add_css_class("acao-rodape")
        self.btn_limpar.connect("clicked", lambda _b: self._limpar())
        rodape.append(self.btn_limpar)

        # arrastar e soltar URLs na página
        alvo = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.COPY)
        alvo.connect("drop", self._recebeu_drop)
        self.add_controller(alvo)

    # ==================================================================
    # Ganchos para as subclasses
    # ==================================================================
    def montar_opcoes(self, opcoes: Adw.WrapBox) -> None:
        """Adiciona controles específicos da aba (formato, qualidade…)."""

    def adicionar_urls(self, urls: list[str]) -> int:
        """Envia URLs ao motor. Devolve quantos itens foram criados."""
        raise NotImplementedError

    def abrir_item(self, item) -> None:
        raise NotImplementedError

    # ==================================================================
    # Ações comuns
    # ==================================================================
    def atualizar_destino(self) -> None:
        pasta = getattr(self.config, self._pasta_attr, "") or self.config.pasta_destino
        self.btn_destino.set_child(
            conteudo_botao("folder-symbolic", rotulo_pasta(pasta), espacamento=6)
        )
        self.btn_destino.set_tooltip_text(f"Salvar em: {pasta}")

    def _adicionar(self) -> None:
        texto = self.campo_url.get_text()
        if not texto.strip():
            return
        urls, invalidas = urls_do_texto(texto)
        if not urls:
            self.janela.toast("Nenhum link válido encontrado.")
            return
        criados = self.adicionar_urls(urls)
        if criados:
            self.campo_url.set_text("")
            if len(urls) > 1:
                self.janela.toast(f"{criados} links adicionados à fila.")
            if invalidas:
                self.janela.toast(f"{len(invalidas)} link(s) ignorado(s).")

    def _recebeu_drop(self, _alvo, valor, _x, _y) -> bool:
        if isinstance(valor, str) and valor.strip():
            self.campo_url.set_text(valor.strip())
            self._adicionar()
            return True
        return False

    def _alternar(self, item) -> None:
        if item.estado == DownloadState.PAUSADO:
            self.motor.retomar(item)
        elif item.estado in (DownloadState.ERRO, DownloadState.CANCELADO):
            self.motor.repetir(item)
        else:
            if not self.motor.pausar(item):
                self.janela.toast("Aguarde o processamento terminar para pausar.")

    def _cancelar(self, item) -> None:
        self.motor.cancelar(item)

    def _limpar(self) -> None:
        removidos = self.motor.limpar_concluidos()
        for item_id in removidos:
            linha = self.linhas.pop(item_id, None)
            if linha:
                self.lista.remove(linha)
        self._refletir()

    # ==================================================================
    # Sincronização com a UI (sempre na thread GTK)
    # ==================================================================
    def ao_atualizar(self, item) -> None:
        GLib.idle_add(self._atualizar_item, item)

    def ao_finalizar(self, item) -> None:
        GLib.idle_add(self._finalizar_item, item)

    def registrar(self, item) -> None:
        linha = LinhaFila(
            item, self._alternar, self._cancelar, self.abrir_item, self._abrir_pasta_item
        )
        self.linhas[item.id] = linha
        self.lista.prepend(linha)
        self._refletir()

    def _abrir_pasta_item(self, item) -> None:
        from .util import abrir_pasta

        pasta = getattr(item, "pasta", "") or ""
        if not pasta:
            caminho = getattr(item, "caminho_arquivo", "") or ""
            pasta = os.path.dirname(caminho) if caminho else ""
        if not pasta:
            pasta = (
                getattr(self.config, self._pasta_attr, "")
                or self.config.pasta_destino
            )
        abrir_pasta(pasta)

    def _atualizar_item(self, item) -> bool:
        linha = self.linhas.get(item.id)
        if linha:
            linha.atualizar()
        self._refletir()
        return GLib.SOURCE_REMOVE

    def _finalizar_item(self, item) -> bool:
        linha = self.linhas.get(item.id)
        if linha:
            linha.atualizar()
        if item.estado == DownloadState.CONCLUIDO:
            self.janela.toast(self._mensagem_sucesso(item))
        elif item.estado == DownloadState.ERRO:
            self.janela.toast(f"Erro: {(item.erro or 'falha desconhecida')[:110]}")
        self._refletir()
        return GLib.SOURCE_REMOVE

    def _mensagem_sucesso(self, item) -> str:
        return f"Concluído: {item.titulo_exibicao[:70]}"

    # ==================================================================
    # Estado da fila
    # ==================================================================
    def _refletir(self) -> None:
        itens = self.motor.itens()
        self.pilha.set_visible_child_name("fila" if itens else "vazio")

        total = len(itens)
        self.rotulo_contador.set_text(f"{total} {'item' if total == 1 else 'itens'}")
        self.rotulo_contador.set_visible(bool(total))

        contagem: dict[DownloadState, int] = {}
        for i in itens:
            contagem[i.estado] = contagem.get(i.estado, 0) + 1

        partes = []
        rotulos = (
            (DownloadState.BAIXANDO, "baixando"),
            (DownloadState.PROCESSANDO, "processando"),
            (DownloadState.AGUARDANDO, "na fila"),
            (DownloadState.PAUSADO, "pausado"),
            (DownloadState.CONCLUIDO, "concluído"),
            (DownloadState.ERRO, "com erro"),
        )
        for estado, texto in rotulos:
            n = contagem.get(estado, 0)
            if n:
                partes.append(f"{n} {texto}{'s' if n > 1 and estado != DownloadState.AGUARDANDO else ''}")
        self.rotulo_resumo.set_text(" · ".join(partes) if partes else "Fila vazia")

        tem_fila = any(
            i.estado in (DownloadState.AGUARDANDO, DownloadState.PAUSADO) for i in itens
        )
        tem_ativo = any(
            i.estado in (DownloadState.BAIXANDO, DownloadState.AGUARDANDO) for i in itens
        )
        tem_finalizados = any(
            i.estado in (DownloadState.CONCLUIDO, DownloadState.CANCELADO) for i in itens
        )
        self.btn_retomar_tudo.set_sensitive(bool(itens) and tem_fila)
        self.btn_pausar_tudo.set_sensitive(tem_ativo)
        self.btn_limpar.set_sensitive(tem_finalizados)

        self.ao_refletir(itens)

    def ao_refletir(self, itens) -> None:
        """Gancho opcional para atualizar extras da página."""
