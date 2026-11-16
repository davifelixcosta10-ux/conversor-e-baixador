"""Janela principal do Conversor de Arquivos."""

from __future__ import annotations

import json
import os
import subprocess

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from . import APP_ID, APP_NAME, APP_VERSION, plataforma
from .engine import MotorConversao, TrabalhoConversao
from .formats import (
    Preset,
    categoria_para_tipo,
    categorias_com_presets,
    presets_da_categoria,
)

_PREFS = str(plataforma.arquivo_config())

# presets em que o seletor de qualidade muda alguma coisa
COM_QUALIDADE = {
    "video-mp4",
    "video-webm",
    "video-compress",
    "video-gif",
    "video-webp",
    "img-webp",
    "img-avif",
    "img-resize",
}


# ---------------------------------------------------------------------------
# utilidades locais
# ---------------------------------------------------------------------------
def formatar_tamanho(n: float) -> str:
    if n <= 0:
        return "—"
    for u in ("B", "KiB", "MiB", "GiB"):
        if n < 1024:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TiB"


def formatar_duracao(seg: float) -> str:
    s = int(seg or 0)
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def icone_por_tipo(tipo: str) -> str:
    return {
        "video": "video-x-generic-symbolic",
        "audio": "audio-x-generic-symbolic",
        "image": "image-x-generic-symbolic",
        "pdf": "x-office-document-symbolic",
        "documento": "x-office-document-symbolic",
        "texto": "text-x-generic-symbolic",
        "arquivo": "package-x-generic-symbolic",
    }.get(tipo, "text-x-generic-symbolic")


def caminhos_de_texto(texto: str) -> list[str]:
    """Extrai caminhos de dados de DnD (text/plain, text/uri-list, x-special)."""
    caminhos: list[str] = []
    for linha in (texto or "").splitlines():
        linha = linha.strip()
        if not linha or linha in ("copy", "cut", "move", "link"):
            continue
        if linha.startswith("file://"):
            try:
                caminho = Gio.File.new_for_uri(linha).get_path()
            except Exception:
                caminho = None
            if caminho:
                caminhos.append(caminho)
        elif os.path.isabs(linha) and os.path.exists(linha):
            caminhos.append(linha)
    return caminhos


class JanelaPrincipal(Adw.ApplicationWindow):
    def __init__(self, app, config_dir=None):
        super().__init__(application=app)
        self.set_title(APP_NAME)
        self.set_default_size(940, 760)
        self.set_size_request(460, 420)

        self.config_dir = config_dir
        self.motor = MotorConversao()
        self._arquivos: list[str] = []
        self._linhas: dict[str, dict] = {}
        self._pasta_saida = os.path.expanduser("~/Downloads")

        self._categorias: list[str] = []
        self._categoria_atual: str | None = None
        self._preset_atual_id: str | None = None
        self._preset_preferido: str | None = None
        self._checks: dict[str, Gtk.CheckButton] = {}
        self._linhas_presets: dict[str, Gtk.ListBoxRow] = {}
        self._montando = False

        self._prefs = self._ler_prefs()

        self._montar_ui()
        self._montar_acoes()
        self._montar_atalhos()
        self._instalar_drop()
        self._aplicar_prefs()

    # ==================================================================
    # Preferências simples (json)
    # ==================================================================
    def _ler_prefs(self) -> dict:
        try:
            with open(_PREFS, "r", encoding="utf-8") as f:
                dados = json.load(f)
            return dados if isinstance(dados, dict) else {}
        except Exception:
            return {}

    def _salvar_prefs(self) -> None:
        dados = {
            "pasta_saida": self._pasta_saida,
            "categoria": self._categoria_atual,
            "preset": self._preset_atual(),
            "qualidade": self.linha_qualidade.get_selected(),
            "mesmo_lado": self.switch_lado.get_active(),
            "apagar_original": self.switch_apagar.get_active(),
            "abrir_pasta": self.switch_abrir.get_active(),
            "segundo_frame": self.linha_frame.get_value(),
        }
        try:
            os.makedirs(os.path.dirname(_PREFS), exist_ok=True)
            with open(_PREFS, "w", encoding="utf-8") as f:
                json.dump(dados, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _aplicar_prefs(self) -> None:
        p = self._prefs
        pasta = p.get("pasta_saida")
        if pasta and os.path.isdir(os.path.expanduser(pasta)):
            self._pasta_saida = os.path.expanduser(pasta)
            self.linha_saida.set_subtitle(self._pasta_saida)
        if isinstance(p.get("qualidade"), int) and 0 <= p["qualidade"] <= 2:
            self.linha_qualidade.set_selected(p["qualidade"])
        self.switch_lado.set_active(bool(p.get("mesmo_lado", False)))
        self.switch_apagar.set_active(bool(p.get("apagar_original", False)))
        self.switch_abrir.set_active(bool(p.get("abrir_pasta", True)))
        try:
            self.linha_frame.set_value(float(p.get("segundo_frame", 1.0)))
        except (TypeError, ValueError):
            pass

        self._preset_preferido = p.get("preset")
        categoria = p.get("categoria")
        if categoria in self._categorias:
            self._categoria_atual = categoria
            self.toggles.set_active_name(categoria)
        self._reconstruir_presets()

    # ==================================================================
    # UI
    # ==================================================================
    def _montar_ui(self) -> None:
        view = Adw.ToolbarView()

        header = Adw.HeaderBar()
        titulo = Adw.WindowTitle(
            title=APP_NAME, subtitle="Vídeo, áudio, imagem, documento e arquivo"
        )
        header.set_title_widget(titulo)

        btn_add = Gtk.Button.new_from_icon_name("list-add-symbolic")
        btn_add.set_tooltip_text("Adicionar arquivos")
        btn_add.connect("clicked", lambda _b: self._escolher_arquivos())
        header.pack_start(btn_add)

        menu = Gio.Menu()
        menu.append("Colar caminhos", "win.colar")
        menu.append("Limpar concluídos", "win.limpar_concluidos")
        menu.append("Limpar lista", "win.limpar")
        menu.append("Sobre", "app.sobre")
        menu.append("Sair", "app.quit")
        btn_menu = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        header.pack_end(btn_menu)

        view.add_top_bar(header)

        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
        )
        view.set_content(scroll)

        clamp = Adw.Clamp(maximum_size=840, tightening_threshold=740)
        clamp.set_margin_top(16)
        clamp.set_margin_bottom(18)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)
        scroll.set_child(clamp)

        corpo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        clamp.set_child(corpo)

        # ---- zona de soltar ----
        self.zona_drop = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.zona_drop.add_css_class("zona-drop")
        self.zona_drop.set_valign(Gtk.Align.CENTER)

        icone = Gtk.Image.new_from_icon_name("document-save-symbolic")
        icone.set_pixel_size(30)
        icone.add_css_class("dim-label")
        icone.set_valign(Gtk.Align.CENTER)
        self.zona_drop.append(icone)

        textos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        textos.set_valign(Gtk.Align.CENTER)
        textos.set_hexpand(True)
        self.zona_drop.append(textos)

        titulo_zona = Gtk.Label(label="Arraste arquivos para cá", xalign=0.0)
        titulo_zona.add_css_class("titulo-secao")
        textos.append(titulo_zona)

        dica_zona = Gtk.Label(
            label=(
                "Vídeo, áudio, imagem, PDF, documento ou pacote — vários de uma vez, "
                "ou clique para escolher. Dá para colar caminhos com Ctrl+V."
            ),
            xalign=0.0,
        )
        dica_zona.add_css_class("dim-label")
        dica_zona.set_wrap(True)
        dica_zona.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        textos.append(dica_zona)

        btn_escolher = Gtk.Button(label="Escolher…")
        btn_escolher.add_css_class("suggested-action")
        btn_escolher.set_valign(Gtk.Align.CENTER)
        btn_escolher.connect("clicked", lambda _b: self._escolher_arquivos())
        self.zona_drop.append(btn_escolher)

        btn_colar = Gtk.Button(icon_name="edit-paste-symbolic")
        btn_colar.add_css_class("flat")
        btn_colar.set_valign(Gtk.Align.CENTER)
        btn_colar.set_tooltip_text("Colar caminhos da área de transferência (Ctrl+V)")
        btn_colar.connect("clicked", lambda _b: self._colar_caminhos())
        self.zona_drop.append(btn_colar)

        click = Gtk.GestureClick()
        click.connect("pressed", lambda *_a: self._escolher_arquivos())
        self.zona_drop.add_controller(click)

        corpo.append(self.zona_drop)

        # ---- lista de arquivos ----
        self.caixa_arquivos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        cabecalho = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.rotulo_lista = Gtk.Label(label="Arquivos", xalign=0.0)
        self.rotulo_lista.set_hexpand(True)
        self.rotulo_lista.add_css_class("titulo-secao")
        cabecalho.append(self.rotulo_lista)

        btn_mais = Gtk.Button(icon_name="list-add-symbolic")
        btn_mais.add_css_class("flat")
        btn_mais.set_tooltip_text("Adicionar mais arquivos")
        btn_mais.connect("clicked", lambda _b: self._escolher_arquivos())
        cabecalho.append(btn_mais)

        btn_limpar = Gtk.Button(icon_name="edit-clear-all-symbolic")
        btn_limpar.add_css_class("flat")
        btn_limpar.set_tooltip_text("Limpar lista")
        btn_limpar.connect("clicked", lambda _b: self._limpar())
        cabecalho.append(btn_limpar)
        self.caixa_arquivos.append(cabecalho)

        self.lista = Gtk.ListBox()
        self.lista.set_selection_mode(Gtk.SelectionMode.NONE)
        self.lista.add_css_class("boxed-list")
        self.caixa_arquivos.append(self.lista)

        corpo.append(self.caixa_arquivos)

        # ---- categorias ----
        self.caixa_categorias = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        rotulo_conv = Gtk.Label(label="Converter para", xalign=0.0)
        rotulo_conv.add_css_class("titulo-secao")
        self.caixa_categorias.append(rotulo_conv)

        self.toggles = Adw.ToggleGroup()
        self.toggles.set_homogeneous(True)
        self.toggles.add_css_class("toggles-categoria")
        self.toggles.connect("notify::active-name", self._mudou_categoria)
        self.caixa_categorias.append(self.toggles)

        corpo.append(self.caixa_categorias)

        # ---- lista de presets ----
        self.lista_presets = Gtk.ListBox()
        self.lista_presets.set_selection_mode(Gtk.SelectionMode.NONE)
        self.lista_presets.add_css_class("boxed-list")
        self.lista_presets.add_css_class("lista-presets")
        corpo.append(self.lista_presets)

        # ---- ajustes ----
        grupo = Adw.PreferencesGroup()
        corpo.append(grupo)

        self.linha_qualidade = Adw.ComboRow(
            title="Qualidade",
            subtitle="Afeta vídeo, GIF/WebP e imagens",
            model=Gtk.StringList.new(["Alta", "Média", "Baixa"]),
        )
        self.linha_qualidade.set_selected(1)
        grupo.add(self.linha_qualidade)

        self.linha_frame = Adw.SpinRow(
            title="Segundo do frame",
            subtitle="Momento do vídeo a ser capturado (0 = automático)",
            adjustment=Gtk.Adjustment(lower=0, upper=86400, step_increment=0.5, page_increment=5),
            digits=1,
            numeric=True,
        )
        self.linha_frame.set_value(1.0)
        grupo.add(self.linha_frame)

        self.linha_saida = Adw.ActionRow(
            title="Pasta de saída", subtitle=self._pasta_saida
        )
        btn_saida = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
        btn_saida.add_css_class("flat")
        btn_saida.set_tooltip_text("Escolher pasta…")
        btn_saida.connect("clicked", self._escolher_saida)
        self.linha_saida.add_suffix(btn_saida)
        grupo.add(self.linha_saida)

        self.switch_lado = Adw.SwitchRow(
            title="Salvar ao lado do original",
            subtitle="Ignora a pasta de saída",
            active=False,
        )
        grupo.add(self.switch_lado)

        self.switch_apagar = Adw.SwitchRow(
            title="Apagar original após converter",
            subtitle="Só para arquivos convertidos com sucesso",
            active=False,
        )
        grupo.add(self.switch_apagar)

        self.switch_abrir = Adw.SwitchRow(
            title="Abrir a pasta ao terminar",
            active=True,
        )
        grupo.add(self.switch_abrir)

        # ---- ação (fixa no rodapé, sempre visível) ----
        barra = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        barra.add_css_class("rodape")
        barra.set_margin_top(10)
        barra.set_margin_bottom(10)
        barra.set_margin_start(16)
        barra.set_margin_end(16)
        view.add_bottom_bar(barra)

        self.progresso_geral = Gtk.ProgressBar()
        self.progresso_geral.set_show_text(True)
        self.progresso_geral.set_hexpand(True)
        self.progresso_geral.set_valign(Gtk.Align.CENTER)
        barra.append(self.progresso_geral)

        self.btn_converter = Gtk.Button(label="Converter")
        self.btn_converter.add_css_class("suggested-action")
        self.btn_converter.add_css_class("botao-baixar")
        self.btn_converter.connect("clicked", self._converter)
        barra.append(self.btn_converter)

        self.btn_cancelar = Gtk.Button(label="Cancelar")
        self.btn_cancelar.add_css_class("destructive-action")
        self.btn_cancelar.set_sensitive(False)
        self.btn_cancelar.connect("clicked", lambda _b: self.motor.cancelar())
        barra.append(self.btn_cancelar)

        self._montar_categorias()
        self._refletir_lista()

        self.toast_overlay = Adw.ToastOverlay(child=view)
        self.set_content(self.toast_overlay)

    # ==================================================================
    # Categorias
    # ==================================================================
    def _montar_categorias(self) -> None:
        self._montando = True
        try:
            self.toggles.remove_all()
        except Exception:
            pass

        self._categorias = []
        for cid, rotulo, icone in categorias_com_presets():
            self._categorias.append(cid)
            try:
                alternador = Adw.Toggle(name=cid, label=rotulo, icon_name=icone)
            except TypeError:
                alternador = Adw.Toggle()
                alternador.set_name(cid)
                alternador.set_label(rotulo)
                alternador.set_icon_name(icone)
            self.toggles.add(alternador)

        if self._categoria_atual not in self._categorias:
            self._categoria_atual = self._categorias[0] if self._categorias else None
        if self._categoria_atual:
            self.toggles.set_active_name(self._categoria_atual)
        self.caixa_categorias.set_visible(bool(self._categorias))
        self._montando = False
        self._reconstruir_presets()

    def _mudou_categoria(self, _grupo, _pspec) -> None:
        if self._montando:
            return
        nome = self.toggles.get_active_name()
        if not nome or nome == self._categoria_atual:
            return
        self._categoria_atual = nome
        self._preset_atual_id = None
        self._reconstruir_presets()

    # ==================================================================
    # Presets
    # ==================================================================
    def _tipos_na_fila(self) -> set[str]:
        return self.motor.tipos_presentes()

    def _compativel(self, preset: Preset, tipos: set[str]) -> bool:
        if not tipos:
            return True
        return bool(tipos & set(preset.tipos))

    def _preset_atual(self) -> str | None:
        return self._preset_atual_id

    def _reconstruir_presets(self) -> None:
        self._montando = True
        try:
            for linha in list(self.lista_presets):
                self.lista_presets.remove(linha)
        except TypeError:
            pass
        self._checks.clear()
        self._linhas_presets.clear()

        categoria = self._categoria_atual
        presets = presets_da_categoria(categoria) if categoria else []
        tipos = self._tipos_na_fila()

        primeiro_check: Gtk.CheckButton | None = None
        primeiro_valido: str | None = None
        grupo_check = None

        for preset in presets:
            compativel = self._compativel(preset, tipos)
            linha = Gtk.ListBoxRow()
            linha.set_activatable(True)
            if not compativel:
                linha.set_sensitive(False)
                linha.set_tooltip_text("Não serve para os arquivos que estão na fila")

            caixa = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            caixa.set_margin_top(10)
            caixa.set_margin_bottom(10)
            caixa.set_margin_start(14)
            caixa.set_margin_end(14)
            linha.set_child(caixa)

            check = Gtk.CheckButton()
            check.set_valign(Gtk.Align.CENTER)
            check.set_sensitive(compativel)
            if primeiro_check is None:
                primeiro_check = check
            else:
                check.set_group(primeiro_check)
            caixa.append(check)

            textos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            textos.set_hexpand(True)
            textos.set_valign(Gtk.Align.CENTER)
            caixa.append(textos)

            titulo = Gtk.Label(label=preset.rotulo, xalign=0.0)
            titulo.set_ellipsize(Pango.EllipsizeMode.END)
            titulo.set_single_line_mode(True)
            titulo.add_css_class("preset-titulo")
            textos.append(titulo)

            descricao = preset.descricao
            if not compativel and tipos:
                descricao += " · não serve para estes arquivos"
            rotulo_desc = Gtk.Label(label=descricao, xalign=0.0)
            rotulo_desc.set_wrap(True)
            rotulo_desc.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
            rotulo_desc.add_css_class("preset-desc")
            textos.append(rotulo_desc)

            if preset.grupo:
                etiqueta = Gtk.Label(label="tudo junto")
                etiqueta.add_css_class("chip-mini")
                etiqueta.set_valign(Gtk.Align.CENTER)
                caixa.append(etiqueta)
            elif preset.multiplo:
                etiqueta = Gtk.Label(label="vários arquivos")
                etiqueta.add_css_class("chip-mini")
                etiqueta.set_valign(Gtk.Align.CENTER)
                caixa.append(etiqueta)

            linha.connect("activate", lambda _r, c=check: c.set_active(True))
            check.connect(
                "toggled",
                lambda c, pid=preset.id: self._check_alternado(c, pid),
            )

            self.lista_presets.append(linha)
            self._checks[preset.id] = check
            self._linhas_presets[preset.id] = linha
            if compativel and primeiro_valido is None:
                primeiro_valido = preset.id

        # mantém a escolha anterior se ainda existir e servir
        escolhido = None
        preferido = self._preset_atual_id or self._preset_preferido
        if preferido in self._checks:
            candidato = next((p for p in presets if p.id == preferido), None)
            if candidato and self._compativel(candidato, tipos):
                escolhido = preferido
        if escolhido is None:
            escolhido = primeiro_valido

        self._preset_atual_id = escolhido
        self._preset_preferido = None
        if escolhido and escolhido in self._checks:
            self._checks[escolhido].set_active(True)

        self._montando = False
        self.lista_presets.set_visible(bool(presets))
        self._atualizar_visibilidade()
        self._atualizar_botao()

    def _check_alternado(self, check: Gtk.CheckButton, preset_id: str) -> None:
        if self._montando or not check.get_active():
            return
        self._preset_atual_id = preset_id
        self._atualizar_visibilidade()
        self._atualizar_botao()

    def _atualizar_visibilidade(self) -> None:
        pid = self._preset_atual_id
        self.linha_frame.set_visible(pid == "video-frame")
        self.linha_qualidade.set_visible(bool(pid) and pid in COM_QUALIDADE)

    def _atualizar_botao(self) -> None:
        n = len(self._arquivos)
        self.btn_converter.set_label(f"Converter {n}" if n else "Converter")

    def _categoria_preferida(self) -> str | None:
        trabalhos = self.motor.trabalhos()
        if not trabalhos:
            return None
        categoria = categoria_para_tipo(trabalhos[0].tipo)
        if categoria in self._categorias:
            return categoria
        return None

    # ==================================================================
    # Drag & drop
    # ==================================================================
    def _instalar_drop(self) -> None:
        acoes = Gdk.DragAction.COPY | Gdk.DragAction.MOVE

        # lista de arquivos (text/uri-list — yazi, Nautilus, terminais…)
        alvo_arquivos = Gtk.DropTarget.new(Gdk.FileList, acoes)
        alvo_arquivos.connect("drop", self._drop_filelist)
        self.add_controller(alvo_arquivos)

        # texto solto (alguns gerenciadores mandam caminhos como texto)
        alvo_texto = Gtk.DropTarget.new(GObject.TYPE_STRING, acoes)
        try:
            alvo_texto.set_gtypes([GObject.TYPE_STRING])
        except Exception:
            pass
        alvo_texto.connect("drop", self._drop_texto)
        self.add_controller(alvo_texto)

        # realce visual da zona durante o arrasto
        for alvo in (alvo_arquivos, alvo_texto):
            alvo.connect("enter", lambda *_a: self.zona_drop.add_css_class("zona-drop-ativa"))
            alvo.connect("leave", lambda *_a: self.zona_drop.remove_css_class("zona-drop-ativa"))

    def _drop_filelist(self, _alvo, valor, _x, _y) -> bool:
        try:
            arquivos = valor.get_files() if valor is not None else []
        except Exception:
            return False
        caminhos = [f.get_path() for f in (arquivos or []) if f.get_path()]
        return self._receber(caminhos)

    def _drop_texto(self, _alvo, valor, _x, _y) -> bool:
        caminhos = caminhos_de_texto(valor or "")
        if caminhos:
            return self._receber(caminhos)
        return False

    def _receber(self, caminhos: list[str]) -> bool:
        arquivos = [c for c in caminhos if os.path.isfile(c)]
        pastas = [c for c in caminhos if os.path.isdir(c)]
        limite = 1000
        for pasta in pastas:
            for raiz, _, nomes in os.walk(pasta):
                for nome in sorted(nomes):
                    arquivos.append(os.path.join(raiz, nome))
                    if len(arquivos) >= limite:
                        break
                if len(arquivos) >= limite:
                    self.toast(f"Limite de {limite} arquivos por vez.")
                    break
            if len(arquivos) >= limite:
                break
        if not arquivos:
            self.toast("Nada aproveitável foi solto aqui.")
            return False
        self._adicionar(arquivos)
        return True

    # ==================================================================
    # Ações
    # ==================================================================
    def _montar_acoes(self) -> None:
        for nome, cb in (
            ("limpar", lambda *_a: self._limpar()),
            ("limpar_concluidos", lambda *_a: self._limpar_concluidos()),
            ("colar", lambda *_a: self._colar_caminhos()),
        ):
            a = Gio.SimpleAction.new(nome, None)
            a.connect("activate", cb)
            self.add_action(a)
        app = self.get_application()
        if app is not None:
            if app.lookup_action("quit") is None:
                a = Gio.SimpleAction.new("quit", None)
                a.connect("activate", lambda *_a: app.quit())
                app.add_action(a)
            if app.lookup_action("sobre") is None:
                a = Gio.SimpleAction.new("sobre", None)
                a.connect("activate", lambda *_a: self._sobre())
                app.add_action(a)

    def _montar_atalhos(self) -> None:
        app = self.get_application()
        if app is None:
            return
        app.set_accels_for_action("app.quit", ["<Ctrl>q"])
        app.set_accels_for_action("win.limpar", ["<Ctrl>l"])
        app.set_accels_for_action("win.colar", ["<Ctrl>v"])

    # ==================================================================
    # Arquivos
    # ==================================================================
    def _escolher_arquivos(self) -> None:
        dlg = Gtk.FileDialog(title="Escolher arquivos")
        dlg.set_modal(True)

        def fim(d, res):
            try:
                arquivos = d.open_multiple_finish(res)
            except GLib.Error:
                return
            if arquivos:
                caminhos = [f.get_path() for f in arquivos if f.get_path()]
                self._adicionar(caminhos)

        dlg.open_multiple(self, None, fim)

    def _colar_caminhos(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        clipboard = display.get_clipboard()

        def pronto(clip, res):
            try:
                texto = clip.read_text_finish(res)
            except GLib.Error:
                self.toast("Não consegui ler a área de transferência.")
                return
            caminhos = caminhos_de_texto(texto or "")
            if not caminhos:
                self.toast("A área de transferência não tem caminhos de arquivo.")
                return
            self._receber(caminhos)

        clipboard.read_text_async(None, pronto)

    def _adicionar(self, caminhos: list[str]) -> None:
        novos = self.motor.adicionar(caminhos)
        for t in novos:
            self._arquivos.append(t.caminho)
            self._adicionar_linha(t)

        if novos:
            # troca de categoria só quando a atual não serve para nada
            categoria = self._categoria_atual
            serve = bool(categoria) and any(
                self._compativel(p, self._tipos_na_fila())
                for p in presets_da_categoria(categoria)
            )
            if not serve:
                preferida = self._categoria_preferida()
                if preferida and preferida != categoria:
                    self._categoria_atual = preferida
                    self._montando = True
                    self.toggles.set_active_name(preferida)
                    self._montando = False
                    self._preset_atual_id = None

        self._reconstruir_presets()
        self._refletir_lista()
        if novos:
            self.toast(f"{len(novos)} arquivo(s) na fila.")
        elif caminhos:
            self.toast("Esses arquivos já estão na lista.")

    def _adicionar_linha(self, t: TrabalhoConversao) -> None:
        linha = Gtk.ListBoxRow()
        linha.set_activatable(False)
        linha.set_selectable(False)

        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        caixa.set_margin_top(10)
        caixa.set_margin_bottom(10)
        caixa.set_margin_start(14)
        caixa.set_margin_end(10)
        linha.set_child(caixa)

        topo = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        caixa.append(topo)

        icone = Gtk.Image.new_from_icon_name(icone_por_tipo(t.tipo))
        icone.set_pixel_size(18)
        icone.add_css_class("dim-label")
        icone.set_valign(Gtk.Align.CENTER)
        topo.append(icone)

        textos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        textos.set_hexpand(True)
        textos.set_valign(Gtk.Align.CENTER)
        topo.append(textos)

        nome = Gtk.Label(label=t.nome, xalign=0.0)
        nome.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        nome.set_single_line_mode(True)
        nome.add_css_class("titulo-item")
        textos.append(nome)

        meta = t.tipo
        if t.tipo == "video":
            meta = (
                f"vídeo · {t.info.get('largura', 0)}×{t.info.get('altura', 0)}"
                f" · {formatar_duracao(t.info.get('duracao', 0))}"
            )
        elif t.tipo == "audio":
            meta = f"áudio · {formatar_duracao(t.info.get('duracao', 0))}"
        elif t.tipo == "image":
            meta = f"imagem · {t.info.get('largura', 0)}×{t.info.get('altura', 0)}"
        elif t.tipo == "pdf":
            meta = "documento · PDF"
        try:
            meta += f" · {formatar_tamanho(os.path.getsize(t.caminho))}"
        except OSError:
            pass
        rotulo_meta = Gtk.Label(label=meta, xalign=0.0)
        rotulo_meta.set_ellipsize(Pango.EllipsizeMode.END)
        rotulo_meta.set_single_line_mode(True)
        rotulo_meta.add_css_class("meta-item")
        textos.append(rotulo_meta)

        status = Gtk.Label(label="na fila")
        status.add_css_class("estado-item")
        status.set_valign(Gtk.Align.CENTER)
        topo.append(status)

        btn_arquivo = Gtk.Button(icon_name="document-open-symbolic")
        btn_arquivo.add_css_class("acao-item")
        btn_arquivo.add_css_class("acao-verde")
        btn_arquivo.set_tooltip_text("Abrir o arquivo convertido")
        btn_arquivo.set_visible(False)
        btn_arquivo.connect("clicked", lambda _b, tt=t: self._abrir_arquivo(tt))
        topo.append(btn_arquivo)

        btn_abrir = Gtk.Button(icon_name="folder-open-symbolic")
        btn_abrir.add_css_class("acao-item")
        btn_abrir.add_css_class("acao-azul")
        btn_abrir.set_tooltip_text("Abrir a pasta do arquivo convertido")
        btn_abrir.set_visible(False)
        btn_abrir.connect("clicked", lambda _b, tt=t: self._abrir_resultado(tt))
        topo.append(btn_abrir)

        btn_remover = Gtk.Button(icon_name="window-close-symbolic")
        btn_remover.add_css_class("acao-item")
        btn_remover.add_css_class("acao-vermelho")
        btn_remover.set_tooltip_text("Remover da lista")
        btn_remover.connect("clicked", lambda _b, c=t.caminho: self._remover(c))
        topo.append(btn_remover)

        barra = Gtk.ProgressBar()
        barra.set_valign(Gtk.Align.CENTER)
        barra.set_hexpand(True)
        barra.add_css_class("progresso-item")
        caixa.append(barra)

        self.lista.append(linha)
        self._linhas[t.caminho] = {
            "linha": linha,
            "status": status,
            "barra": barra,
            "abrir": btn_abrir,
            "arquivo": btn_arquivo,
        }

    def _remover(self, caminho: str) -> None:
        if self.motor.rodando:
            self.toast("Espere a conversão atual terminar.")
            return
        self.motor.remover(caminho)
        if caminho in self._arquivos:
            self._arquivos.remove(caminho)
        info = self._linhas.pop(caminho, None)
        if info:
            self.lista.remove(info["linha"])
        self._reconstruir_presets()
        self._refletir_lista()

    def _limpar(self) -> None:
        if self.motor.rodando:
            return
        self.motor.limpar_tudo()
        self._arquivos.clear()
        for info in list(self._linhas.values()):
            self.lista.remove(info["linha"])
        self._linhas.clear()
        self._reconstruir_presets()
        self._refletir_lista()

    def _limpar_concluidos(self) -> None:
        if self.motor.rodando:
            return
        for caminho in list(self._linhas):
            info = self._linhas[caminho]
            t = next((x for x in self.motor.trabalhos() if x.caminho == caminho), None)
            if t and t.estado in ("concluido", "erro", "cancelado"):
                self.motor.remover(caminho)
                if caminho in self._arquivos:
                    self._arquivos.remove(caminho)
                self.lista.remove(info["linha"])
                self._linhas.pop(caminho, None)
        self._reconstruir_presets()
        self._refletir_lista()

    def _refletir_lista(self) -> None:
        tem = bool(self._arquivos)
        self.caixa_arquivos.set_visible(tem)
        self.rotulo_lista.set_text(f"Arquivos ({len(self._arquivos)})")
        self.btn_converter.set_sensitive(tem and not self.motor.rodando)
        self.btn_cancelar.set_sensitive(self.motor.rodando)
        self._atualizar_botao()
        if not self.motor.rodando:
            self.progresso_geral.set_fraction(0.0)
            self.progresso_geral.set_text("Pronto")

    def _abrir_arquivo(self, t: TrabalhoConversao) -> None:
        if not t.saida:
            return
        if os.path.isdir(t.saida):
            self._abrir_pasta(t.saida)
            return
        try:
            Gio.AppInfo.launch_default_for_uri(
                Gio.File.new_for_path(t.saida).get_uri(), None
            )
        except Exception:
            self._abrir_pasta(os.path.dirname(t.saida))

    def _abrir_resultado(self, t: TrabalhoConversao) -> None:
        if t.saida and os.path.isdir(t.saida):
            self._abrir_pasta(t.saida)
            return
        self._abrir_pasta(os.path.dirname(t.saida or t.caminho))

    @staticmethod
    def _abrir_pasta(pasta: str) -> None:
        if not pasta:
            return
        try:
            Gio.AppInfo.launch_default_for_uri(
                Gio.File.new_for_path(pasta).get_uri(), None
            )
        except Exception:
            plataforma.abrir_caminho(pasta)

    # ==================================================================
    # Saída
    # ==================================================================
    def _escolher_saida(self, _btn) -> None:
        dlg = Gtk.FileDialog(title="Pasta de saída")
        try:
            dlg.set_initial_folder(Gio.File.new_for_path(self._pasta_saida))
        except Exception:
            pass

        def fim(d, res):
            try:
                pasta = d.select_folder_finish(res)
            except GLib.Error:
                return
            if pasta:
                self._pasta_saida = pasta.get_path()
                self.linha_saida.set_subtitle(self._pasta_saida)
                self._salvar_prefs()

        dlg.select_folder(self, None, fim)

    # ==================================================================
    # Conversão
    # ==================================================================
    def _converter(self, _btn) -> None:
        pid = self._preset_atual_id
        if not pid:
            self.toast("Escolha um formato de saída.")
            return
        if not self._arquivos:
            self.toast("Adicione arquivos primeiro.")
            return

        preset = next(
            (p for p in presets_da_categoria(self._categoria_atual or "") if p.id == pid),
            None,
        )
        tipos = self._tipos_na_fila()
        if preset is not None and tipos:
            fora = [t for t in tipos if t not in preset.tipos]
            if fora:
                self.toast(
                    "Alguns arquivos não são do tipo desta conversão e serão marcados como erro."
                )

        qualidade = ["alta", "media", "baixa"][
            max(0, min(2, self.linha_qualidade.get_selected()))
        ]
        mesmo_lado = self.switch_lado.get_active()
        pasta = self._pasta_saida
        segundo = float(self.linha_frame.get_value())

        self._salvar_prefs()
        self.btn_converter.set_sensitive(False)
        self.btn_cancelar.set_sensitive(True)
        self.progresso_geral.set_fraction(0.0)
        self.progresso_geral.set_text("Convertendo…")

        # reseta visual das linhas
        for info in self._linhas.values():
            info["status"].set_text("na fila")
            info["status"].remove_css_class("concluido")
            info["status"].remove_css_class("erro")
            info["status"].remove_css_class("cancelado")
            info["linha"].remove_css_class("concluido")
            info["linha"].remove_css_class("erro")
            info["linha"].remove_css_class("cancelado")
            info["barra"].set_fraction(0.0)
            info["abrir"].set_visible(False)
            info["arquivo"].set_visible(False)

        def ao_atualizar(t):
            GLib.idle_add(self._atualizar_trabalho, t)

        def ao_finalizar(lista):
            GLib.idle_add(self._finalizar, lista)

        ok = self.motor.iniciar(
            pid, qualidade, pasta, mesmo_lado, ao_atualizar, ao_finalizar, segundo
        )
        if not ok:
            self.toast("Conversão já em andamento.")
            self.btn_converter.set_sensitive(True)
            self.btn_cancelar.set_sensitive(False)

    def _atualizar_trabalho(self, t: TrabalhoConversao) -> bool:
        info = self._linhas.get(t.caminho)
        if info:
            info["barra"].set_fraction(max(0.0, min(1.0, t.progresso)))
            rotulo = {
                "aguardando": "na fila",
                "convertendo": f"{t.progresso * 100:.0f}%",
                "concluido": "pronto",
                "erro": "erro",
                "cancelado": "cancelado",
            }.get(t.estado, t.estado)
            info["status"].set_text(rotulo)
            info["status"].set_tooltip_text(t.erro or "")
            for cls in ("concluido", "erro", "cancelado"):
                info["status"].remove_css_class(cls)
                info["linha"].remove_css_class(cls)
            if t.estado in ("concluido", "erro", "cancelado"):
                info["status"].add_css_class(t.estado)
                info["linha"].add_css_class(t.estado)
            pronto = bool(t.saida) and t.estado == "concluido"
            info["abrir"].set_visible(pronto)
            info["arquivo"].set_visible(pronto and not os.path.isdir(t.saida))

        trabalhos = self.motor.trabalhos()
        if trabalhos:
            media = sum(x.progresso for x in trabalhos) / len(trabalhos)
            self.progresso_geral.set_fraction(media)
            self.progresso_geral.set_text(f"{int(media * 100)}%")
        return GLib.SOURCE_REMOVE

    def _finalizar(self, lista) -> bool:
        self.btn_converter.set_sensitive(True)
        self.btn_cancelar.set_sensitive(False)

        concluidos = [t for t in lista if t.estado == "concluido"]
        erros = [t for t in lista if t.estado == "erro"]
        cancelados = [t for t in lista if t.estado == "cancelado"]

        if concluidos:
            self.progresso_geral.set_fraction(1.0)
        if erros:
            self.progresso_geral.set_text(f"{len(erros)} com erro")
        elif cancelados:
            self.progresso_geral.set_text("Cancelado")
        else:
            self.progresso_geral.set_text("Concluído")

        if self.switch_apagar.get_active():
            for t in concluidos:
                if t.saida and os.path.abspath(t.saida) != os.path.abspath(t.caminho):
                    try:
                        os.remove(t.caminho)
                    except OSError:
                        pass

        if erros:
            self.toast(f"{len(erros)} arquivo(s) com erro.")
        elif concluidos:
            self.toast(f"{len(concluidos)} arquivo(s) convertido(s).")

        if concluidos and self.switch_abrir.get_active() and not self.switch_lado.get_active():
            self._abrir_pasta(os.path.dirname(concluidos[0].saida))
        return GLib.SOURCE_REMOVE

    # ==================================================================
    def _sobre(self) -> None:
        sobre = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=APP_VERSION,
            developer_name="Omarchy",
            comments=(
                "Conversor de vídeo, áudio, imagem, documento e pacotes "
                "usando ffmpeg, ImageMagick, Poppler, Ghostscript e 7-Zip."
            ),
            license_type=Gtk.License.MIT_X11,
        )
        sobre.present(self)

    def toast(self, texto: str) -> None:
        t = Adw.Toast.new(texto)
        t.set_timeout(4)
        self.toast_overlay.add_toast(t)

    def fechar(self) -> None:
        self._salvar_prefs()
        self.motor.cancelar()
