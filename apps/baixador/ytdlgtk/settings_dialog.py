"""Diálogo de preferências (Adw.PreferencesDialog) — tudo aplicado ao vivo."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Gio, GLib

from .settings import Configuracoes, NAVEGADORES, TEMAS
from .models import QUALIDADES
from . import sites


class DialogoPreferencias(Adw.PreferencesDialog):
    def __init__(self, config: Configuracoes, ao_mudar=None):
        super().__init__()
        self.set_title("Preferências")
        self.config = config
        self._ao_mudar = ao_mudar or (lambda: None)

        self._montar_geral()
        self._montar_imagens()
        self._montar_cookies()
        self._montar_rede()
        self._montar_aparencia()

    def _montar(self, pagina: Adw.PreferencesPage, grupo: Adw.PreferencesGroup):
        pagina.add(grupo)
        self.add(pagina)

    # ------------------------------------------------------------------
    def _montar_geral(self) -> None:
        pag = Adw.PreferencesPage(title="Geral", icon_name="applications-system-symbolic")

        g1 = Adw.PreferencesGroup(title="Downloads", description="Onde e como os arquivos são salvos")

        # Pasta de vídeos
        self.linha_pasta_videos = Adw.ActionRow(
            title="Pasta de vídeos", subtitle=self.config.pasta_videos_efetiva()
        )
        self.linha_pasta_videos.add_prefix(Gtk.Image.new_from_icon_name("video-x-generic-symbolic"))
        btn_v = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
        btn_v.add_css_class("flat")
        btn_v.set_tooltip_text("Escolher pasta…")
        btn_v.connect("clicked", lambda _b: self._escolher_pasta_attr("pasta_videos", self.linha_pasta_videos))
        self.linha_pasta_videos.add_suffix(btn_v)
        g1.add(self.linha_pasta_videos)

        # Pasta de imagens
        self.linha_pasta_imagens = Adw.ActionRow(
            title="Pasta de imagens", subtitle=self.config.pasta_imagens_efetiva()
        )
        self.linha_pasta_imagens.add_prefix(Gtk.Image.new_from_icon_name("image-x-generic-symbolic"))
        btn_i = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
        btn_i.add_css_class("flat")
        btn_i.set_tooltip_text("Escolher pasta…")
        btn_i.connect("clicked", lambda _b: self._escolher_pasta_attr("pasta_imagens", self.linha_pasta_imagens))
        self.linha_pasta_imagens.add_suffix(btn_i)
        g1.add(self.linha_pasta_imagens)

        # Simultâneos
        ajuste = Gtk.Adjustment(value=self.config.simultaneos, lower=1, upper=5, step_increment=1)
        self.linha_simultaneos = Adw.SpinRow(
            title="Downloads simultâneos",
            subtitle="Quantos itens baixam ao mesmo tempo",
            adjustment=ajuste,
        )
        self.linha_simultaneos.connect("notify::value", self._mudou_simultaneos)
        g1.add(self.linha_simultaneos)

        # Formato padrão
        self.linha_formato = Adw.ComboRow(
            title="Formato padrão",
            subtitle="Aplicado a novos itens da fila",
            model=Gtk.StringList.new(["Vídeo MP4", "Vídeo MKV", "Apenas Áudio MP3"]),
        )
        self.linha_formato.set_selected({"mp4": 0, "mkv": 1, "mp3": 2}.get(self.config.formato_padrao, 0))
        self.linha_formato.connect("notify::selected", self._mudou_formato)
        g1.add(self.linha_formato)

        # Qualidade padrão
        self.linha_qualidade = Adw.ComboRow(
            title="Qualidade padrão",
            subtitle="Resolução máxima; se não existir, usa a melhor disponível",
            model=Gtk.StringList.new([q.rotulo for q in QUALIDADES]),
        )
        try:
            qidx = [q.chave for q in QUALIDADES].index(self.config.qualidade_padrao)
        except ValueError:
            qidx = 0
        self.linha_qualidade.set_selected(qidx)
        self.linha_qualidade.connect("notify::selected", self._mudou_qualidade)
        g1.add(self.linha_qualidade)

        # Playlists
        self.linha_playlists = Adw.SwitchRow(
            title="Permitir playlists",
            subtitle="URLs de playlist entram como um único item",
            active=self.config.permitir_playlists,
        )
        self.linha_playlists.connect("notify::active", self._mudou_playlists)
        g1.add(self.linha_playlists)

        # ---- extras ----
        self.linha_legendas = Adw.SwitchRow(
            title="Baixar legendas",
            subtitle="Salva .srt em português (ou inglês) quando disponível",
            active=self.config.baixar_legendas,
        )
        self.linha_legendas.connect(
            "notify::active", lambda s, _p: self._set("baixar_legendas", s.get_active())
        )
        g1.add(self.linha_legendas)

        self.linha_capa = Adw.SwitchRow(
            title="Baixar capa",
            subtitle="Salva a miniatura do vídeo junto (JPG)",
            active=self.config.baixar_capa,
        )
        self.linha_capa.connect(
            "notify::active", lambda s, _p: self._set("baixar_capa", s.get_active())
        )
        g1.add(self.linha_capa)

        self._montar(pag, g1)

    # ------------------------------------------------------------------
    def _montar_imagens(self) -> None:
        pag = Adw.PreferencesPage(title="Imagens", icon_name="image-x-generic-symbolic")
        g = Adw.PreferencesGroup(
            title="Galerias e fotos",
            description=(
                "O gallery-dl baixa sempre a resolução original publicada no site; "
                "as opções abaixo definem o que fazer depois."
            ),
        )

        self.linha_formato_img = Adw.ComboRow(
            title="Formato final",
            subtitle="Original mantém o arquivo exatamente como veio",
            model=Gtk.StringList.new(["Original", "JPG", "PNG", "WebP"]),
        )
        self.linha_formato_img.set_selected(
            {"original": 0, "jpg": 1, "png": 2, "webp": 3}.get(self.config.formato_imagem, 0)
        )
        self.linha_formato_img.connect("notify::selected", self._mudou_formato_img)
        g.add(self.linha_formato_img)

        self.linha_resolucao_img = Adw.ComboRow(
            title="Tamanho máximo",
            subtitle="Reduz a imagem só se ela for maior que o limite",
            model=Gtk.StringList.new(["Original", "1920 px", "2560 px", "3840 px"]),
        )
        self.linha_resolucao_img.set_selected(
            {0: 0, 1920: 1, 2560: 2, 3840: 3}.get(self.config.max_largura_imagem, 0)
        )
        self.linha_resolucao_img.connect("notify::selected", self._mudou_resolucao_img)
        g.add(self.linha_resolucao_img)

        self.linha_limite_img = Adw.SpinRow(
            title="Limite de imagens por link",
            subtitle="0 = sem limite",
            adjustment=Gtk.Adjustment(
                value=self.config.limite_imagens, lower=0, upper=1000, step_increment=5
            ),
        )
        self.linha_limite_img.connect("notify::value", self._mudou_limite_img)
        g.add(self.linha_limite_img)

        self.linha_subpastas = Adw.SwitchRow(
            title="Criar subpasta por site",
            subtitle="Ex.: Downloads/instagram/…",
            active=self.config.subpastas_site,
        )
        self.linha_subpastas.connect(
            "notify::active", lambda s, _p: self._set("subpastas_site", s.get_active())
        )
        g.add(self.linha_subpastas)

        self._montar(pag, g)

    # ------------------------------------------------------------------
    def _montar_cookies(self) -> None:
        pag = Adw.PreferencesPage(title="Cookies", icon_name="avatar-default-symbolic")
        g = Adw.PreferencesGroup(
            title="Cookies do navegador",
            description=(
                "Necessário para conteúdo com login ou restrição de idade. "
                "Faça login no site pelo navegador escolhido antes de baixar."
            ),
        )

        rotulos = [rotulo for rotulo, _ in NAVEGADORES]
        self.linha_navegador = Adw.ComboRow(
            title="Importar cookies de",
            model=Gtk.StringList.new(rotulos),
        )
        valor_atual = self.config.navegador_cookies
        idx = 0
        for i, (_, chave) in enumerate(NAVEGADORES):
            if chave == valor_atual:
                idx = i
                break
        self.linha_navegador.set_selected(idx)
        self.linha_navegador.connect("notify::selected", self._mudou_navegador)
        g.add(self.linha_navegador)

        self.linha_perfil = Adw.EntryRow(title="Perfil do navegador (opcional)")
        self.linha_perfil.set_text(self.config.perfil_navegador)
        self.linha_perfil.set_sensitive(bool(self.config.navegador_cookies))
        self.linha_perfil.connect("changed", self._mudou_perfil)
        g.add(self.linha_perfil)

        self._montar(pag, g)

    # ------------------------------------------------------------------
    def _montar_rede(self) -> None:
        pag = Adw.PreferencesPage(title="Rede", icon_name="network-wireless-symbolic")
        g = Adw.PreferencesGroup(title="Resiliência", description="Opções para sites difíceis e +18")

        self.linha_ssl = Adw.SwitchRow(
            title="Ignorar certificados inválidos",
            subtitle="Útil para sites com TLS quebrado (não recomendado por padrão)",
            active=self.config.ignorar_ssl,
        )
        self.linha_ssl.connect("notify::active", lambda s, _p: self._set("ignorar_ssl", s.get_active()))
        g.add(self.linha_ssl)

        disponivel = sites.__class__ and self._curl_disponivel()
        self.linha_impersonar = Adw.SwitchRow(
            title="Impersonar navegador (curl_cffi)",
            subtitle=(
                "Contorna proteções como Cloudflare"
                if disponivel
                else "Requer: pip install curl_cffi"
            ),
            active=self.config.impersonar and disponivel,
        )
        self.linha_impersonar.set_sensitive(disponivel)
        self.linha_impersonar.connect("notify::active", lambda s, _p: self._set("impersonar", s.get_active()))
        g.add(self.linha_impersonar)

        self.linha_proxy = Adw.EntryRow(title="Proxy")
        self.linha_proxy.set_text(self.config.proxy)
        self.linha_proxy.set_tooltip_text("Ex.: http://127.0.0.1:8080 ou socks5://…")
        self.linha_proxy.connect("changed", self._mudou_proxy)
        g.add(self.linha_proxy)

        # ---- Integração com o MPV ----
        g_mpv = Adw.PreferencesGroup(
            title="Reprodutor MPV",
            description="Permite abrir URLs diretamente no MPV com a mesma resiliência do app",
        )
        self._mpv_disponivel = self._mpv_instalado_no_sistema()
        self.linha_mpv = Adw.SwitchRow(
            title="Integrar com o MPV",
            subtitle=(
                "Instala um yt-dlp resiliente para o MPV (sites +18 e com login)"
                if self._mpv_disponivel
                else "MPV não encontrado — instale com: sudo pacman -S mpv"
            ),
            active=bool(self.config.integrar_mpv and self._mpv_disponivel),
        )
        self.linha_mpv.set_sensitive(self._mpv_disponivel)
        self.linha_mpv.connect("notify::active", self._mudou_mpv)
        g_mpv.add(self.linha_mpv)
        pag.add(g_mpv)

        self._montar(pag, g)

    # ------------------------------------------------------------------
    def _montar_aparencia(self) -> None:
        pag = Adw.PreferencesPage(title="Aparência", icon_name="applications-graphics-symbolic")
        g = Adw.PreferencesGroup(title="Tema")

        self.linha_tema = Adw.ComboRow(
            title="Esquema de cores",
            subtitle="Siga o sistema, ou force claro/escuro",
            model=Gtk.StringList.new([r for r, _ in TEMAS]),
        )
        self.linha_tema.set_selected({"auto": 0, "light": 1, "dark": 2}.get(self.config.tema, 0))
        self.linha_tema.connect("notify::selected", self._mudou_tema)
        g.add(self.linha_tema)

        self._montar(pag, g)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    def _set(self, campo: str, valor) -> None:
        setattr(self.config, campo, valor)
        self.config.salvar()
        self._ao_mudar()

    def _escolher_pasta(self, _btn) -> None:
        self._escolher_pasta_attr("pasta_destino", None)

    def _escolher_pasta_attr(self, attr: str, linha) -> None:
        atual = getattr(self.config, attr, "") or self.config.pasta_destino
        dialogo = Gtk.FileDialog(title="Escolher pasta de destino")
        try:
            dialogo.set_initial_folder(Gio.File.new_for_path(os.path.expanduser(atual)))
        except Exception:
            pass

        def concluido(d, res):
            try:
                pasta = d.select_folder_finish(res)
            except GLib.Error:
                return
            if pasta:
                caminho = pasta.get_path()
                setattr(self.config, attr, caminho)
                if linha is not None:
                    linha.set_subtitle(caminho)
                self.config.salvar()
                self._ao_mudar()

        dialogo.select_folder(self, None, concluido)

    def _mudou_simultaneos(self, spin, _p) -> None:
        self._set("simultaneos", int(spin.get_value()))

    def _mudou_formato(self, combo, _p) -> None:
        self._set("formato_padrao", {0: "mp4", 1: "mkv", 2: "mp3"}.get(combo.get_selected(), "mp4"))

    def _mudou_qualidade(self, combo, _p) -> None:
        idx = combo.get_selected()
        chave = QUALIDADES[idx].chave if 0 <= idx < len(QUALIDADES) else "melhor"
        self._set("qualidade_padrao", chave)

    def _mudou_playlists(self, s, _p) -> None:
        self._set("permitir_playlists", s.get_active())

    def _mudou_formato_img(self, combo, _p) -> None:
        self._set(
            "formato_imagem",
            {0: "original", 1: "jpg", 2: "png", 3: "webp"}.get(combo.get_selected(), "original"),
        )

    def _mudou_resolucao_img(self, combo, _p) -> None:
        self._set(
            "max_largura_imagem",
            {0: 0, 1: 1920, 2: 2560, 3: 3840}.get(combo.get_selected(), 0),
        )

    def _mudou_limite_img(self, linha, _p) -> None:
        self._set("limite_imagens", int(linha.get_value()))

    def _mudou_navegador(self, combo, _p) -> None:
        idx = combo.get_selected()
        chave = NAVEGADORES[idx][1] if 0 <= idx < len(NAVEGADORES) else ""
        self._set("navegador_cookies", chave)
        self.linha_perfil.set_sensitive(bool(chave))

    def _mudou_perfil(self, entrada) -> None:
        self._set("perfil_navegador", entrada.get_text().strip())

    def _mudou_proxy(self, entrada) -> None:
        self._set("proxy", entrada.get_text().strip())

    def _mudou_mpv(self, linha, _p) -> None:
        ativo = linha.get_active()
        from . import mpv as modulo_mpv

        if ativo:
            if not modulo_mpv.instalar():
                linha.set_active(False)
                return
        else:
            modulo_mpv.remover()
        self._set("integrar_mpv", ativo)

    @staticmethod
    def _mpv_instalado_no_sistema() -> bool:
        import shutil

        return shutil.which("mpv") is not None

    def _mudou_tema(self, combo, _p) -> None:
        self._set("tema", {0: "auto", 1: "light", 2: "dark"}.get(combo.get_selected(), "auto"))

    @staticmethod
    def _curl_disponivel() -> bool:
        try:
            import importlib.util

            return importlib.util.find_spec("curl_cffi") is not None
        except Exception:
            return False
