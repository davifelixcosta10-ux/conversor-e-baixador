"""Janela principal: cabeçalho com abas, preferências e notificações."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GObject, Gtk

from . import APP_ID, APP_NAME, APP_VERSION
from .engine import MotorDownloads
from .images import MotorImagens
from .images_view import PaginaImagens
from .settings import Configuracoes, aplicar_tema
from .settings_dialog import DialogoPreferencias
from .util import abrir_pasta, escolher_pasta
from .videos_view import PaginaVideos


class JanelaPrincipal(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, config: Configuracoes):
        super().__init__(application=app)
        self.set_title(APP_NAME)
        self.set_default_size(980, 720)
        self.set_size_request(400, 380)

        self.config = config

        # Motores: os callbacks são encaminhados às páginas (criadas abaixo).
        self.motor_video = MotorDownloads(
            config,
            ao_atualizar=self._video_atualizou,
            ao_finalizar=self._video_finalizou,
        )
        self.motor_imagem = MotorImagens(
            config,
            ao_atualizar=self._imagem_atualizou,
            ao_finalizar=self._imagem_finalizou,
        )

        self._montar_ui()
        self._montar_acoes()
        self._montar_atalhos()

        self.motor_video.iniciar_tudo()
        self.motor_imagem.iniciar_tudo()

    # ==================================================================
    # UI
    # ==================================================================
    def _montar_ui(self) -> None:
        view = Adw.ToolbarView()

        cabecalho = Adw.HeaderBar()
        self.switcher_title = Adw.ViewSwitcherTitle(title=APP_NAME)
        cabecalho.set_title_widget(self.switcher_title)

        btn_pasta = Gtk.Button.new_from_icon_name("folder-open-symbolic")
        btn_pasta.set_tooltip_text("Abrir pasta de destino")
        btn_pasta.connect("clicked", lambda _b: self.abrir_pasta())
        cabecalho.pack_start(btn_pasta)

        menu = Gio.Menu()
        menu.append("Escolher pasta de destino…", "win.escolher-pasta")
        menu.append("Abrir pasta", "win.abrir-pasta")
        menu.append("Preferências", "app.preferencias")
        menu.append("Sobre", "app.sobre")
        menu.append("Sair", "app.quit")
        btn_menu = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        btn_menu.set_tooltip_text("Menu principal")
        cabecalho.pack_end(btn_menu)

        view.add_top_bar(cabecalho)

        self.pilha = Adw.ViewStack()
        self.switcher_title.set_stack(self.pilha)

        self.pagina_videos = PaginaVideos(self, self.config, self.motor_video)
        self.pagina_imagens = PaginaImagens(self, self.config, self.motor_imagem)

        pagina = self.pilha.add_titled(self.pagina_videos, "videos", "Vídeos")
        pagina.set_icon_name("video-x-generic-symbolic")
        pagina = self.pilha.add_titled(self.pagina_imagens, "imagens", "Imagens")
        pagina.set_icon_name("image-x-generic-symbolic")

        view.set_content(self.pilha)

        barra_abas = Adw.ViewSwitcherBar(stack=self.pilha)
        self.switcher_title.bind_property(
            "title-visible", barra_abas, "reveal", GObject.BindingFlags.SYNC_CREATE
        )
        view.add_bottom_bar(barra_abas)

        self.toast_overlay = Adw.ToastOverlay(child=view)
        self.set_content(self.toast_overlay)

        self.pilha.connect("notify::visible-child-name", self._trocou_aba)

    def _trocou_aba(self, *_a) -> None:
        pagina = self.pilha.get_visible_child()
        for p in (self.pagina_videos, self.pagina_imagens):
            if p is pagina:
                p.campo_url.grab_focus()

    # ==================================================================
    # Ações e atalhos
    # ==================================================================
    def _montar_acoes(self) -> None:
        for nome, cb in (
            ("escolher-pasta", lambda *_a: self.escolher_destino()),
            ("abrir-pasta", lambda *_a: self.abrir_pasta()),
        ):
            acao = Gio.SimpleAction.new(nome, None)
            acao.connect("activate", cb)
            self.add_action(acao)

        app = self.get_application()
        if app is not None:
            for nome, cb in (
                ("preferencias", lambda *_a: self.abrir_preferencias()),
                ("sobre", lambda *_a: self._mostrar_sobre()),
            ):
                if app.lookup_action(nome) is None:
                    acao = Gio.SimpleAction.new(nome, None)
                    acao.connect("activate", cb)
                    app.add_action(acao)

    def _montar_atalhos(self) -> None:
        app = self.get_application()
        if app is None:
            return
        app.set_accels_for_action("app.preferencias", ["<Primary>comma"])
        app.set_accels_for_action("app.quit", ["<Primary>q"])
        app.set_accels_for_action("win.escolher-pasta", ["<Primary>d"])

    # ==================================================================
    # Encaminhamento motor → página
    # ==================================================================
    def _video_atualizou(self, item) -> None:
        pagina = getattr(self, "pagina_videos", None)
        if pagina:
            pagina.ao_atualizar(item)

    def _video_finalizou(self, item) -> None:
        pagina = getattr(self, "pagina_videos", None)
        if pagina:
            pagina.ao_finalizar(item)

    def _imagem_atualizou(self, item) -> None:
        pagina = getattr(self, "pagina_imagens", None)
        if pagina:
            pagina.ao_atualizar(item)

    def _imagem_finalizou(self, item) -> None:
        pagina = getattr(self, "pagina_imagens", None)
        if pagina:
            pagina.ao_finalizar(item)

    # ==================================================================
    # Destino / preferências / sobre
    # ==================================================================
    def escolher_destino(self, pasta_attr: str = "pasta_destino") -> None:
        atual = getattr(self.config, pasta_attr, "") or self.config.pasta_destino
        escolher_pasta(self, atual, lambda c: self._definiu_destino(pasta_attr, c))

    def _definiu_destino(self, pasta_attr: str, caminho: str) -> None:
        setattr(self.config, pasta_attr, caminho)
        self.config.salvar()
        for pagina in (self.pagina_videos, self.pagina_imagens):
            pagina.atualizar_destino()

    def abrir_pasta(self) -> None:
        pagina = self.pilha.get_visible_child()
        if pagina is self.pagina_imagens:
            abrir_pasta(self.config.pasta_imagens_efetiva())
        else:
            abrir_pasta(self.config.pasta_videos_efetiva())

    def abrir_preferencias(self) -> None:
        dlg = DialogoPreferencias(self.config, ao_mudar=self._aplicou_preferencias)
        dlg.present(self)

    def _aplicou_preferencias(self) -> None:
        aplicar_tema(self.config.tema)
        self.pagina_videos.recap_preferencias()
        self.pagina_imagens.recap_preferencias()
        self.motor_video.iniciar_tudo()
        self.motor_imagem.iniciar_tudo()

    def _mostrar_sobre(self) -> None:
        sobre = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=APP_VERSION,
            developer_name="Omarchy",
            comments=(
                "Baixe vídeos, áudio e galerias de imagens em resolução original.\n"
                "Motor de vídeo: yt-dlp · galerias: gallery-dl"
            ),
            license_type=Gtk.License.MIT_X11,
        )
        sobre.add_legal_section(
            "gallery-dl", None, Gtk.License.MIT_X11, None
        )
        sobre.present(self)

    # ==================================================================
    def toast(self, texto: str, curto: bool = False) -> None:
        t = Adw.Toast.new(texto)
        t.set_timeout(3 if curto else 5)
        self.toast_overlay.add_toast(t)

    def fechar(self) -> None:
        self.motor_video.encerrar()
        self.motor_imagem.encerrar()
