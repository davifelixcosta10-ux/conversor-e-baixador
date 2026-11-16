"""Aba Vídeos: fila de vídeos/áudio (yt-dlp)."""

from __future__ import annotations

import os
import shutil
import subprocess

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gio, Gtk, Pango

from .fila import PaginaFila
from .models import FORMATOS, QUALIDADES, DownloadState


class PaginaVideos(PaginaFila):
    vazio_icone = "folder-download-symbolic"
    vazio_titulo = "Nada na fila"
    vazio_descricao = "Cole um link acima e pressione Enter. YouTube, TikTok, Instagram, X, Reddit e +1000 sites."
    placeholder = "Cole o link do vídeo, playlist ou canal…"

    def __init__(self, janela, config, motor):
        self._pasta_attr = "pasta_videos"
        try:
            self._formato_idx = [f.chave for f in FORMATOS].index(config.formato_padrao)
        except ValueError:
            self._formato_idx = 0
        try:
            self._qualidade_idx = [q.chave for q in QUALIDADES].index(config.qualidade_padrao)
        except ValueError:
            self._qualidade_idx = 0
        super().__init__(janela, config, motor)

    # ------------------------------------------------------------------
    def montar_opcoes(self, opcoes) -> None:
        bloco_fmt = self._bloco("Formato")
        self.seletor_formato = Gtk.DropDown(
            model=Gtk.StringList.new([f.rotulo_curto for f in FORMATOS])
        )
        self.seletor_formato.set_selected(self._formato_idx)
        self.seletor_formato.set_tooltip_text("Formato do arquivo final")
        self.seletor_formato.connect("notify::selected", self._mudou_formato)
        bloco_fmt.append(self.seletor_formato)
        opcoes.append(bloco_fmt)

        bloco_qual = self._bloco("Qualidade")
        self.seletor_qualidade = Gtk.DropDown(
            model=Gtk.StringList.new([q.rotulo for q in QUALIDADES])
        )
        self.seletor_qualidade.set_selected(self._qualidade_idx)
        self.seletor_qualidade.set_tooltip_text(
            "Resolução máxima — se não existir, baixa a melhor disponível"
        )
        self.seletor_qualidade.connect("notify::selected", self._mudou_qualidade)
        bloco_qual.append(self.seletor_qualidade)
        opcoes.append(bloco_qual)

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
        fmt = FORMATOS[self._formato_idx]
        altura = QUALIDADES[self._qualidade_idx].altura
        criados = 0
        for url in urls:
            item = self.motor.adicionar(url, fmt, altura)
            self.registrar(item)
            criados += 1
        return criados

    def abrir_item(self, item) -> None:
        caminho = self._resolver_arquivo(item)
        if not caminho:
            self.janela.toast("Arquivo não encontrado — abrindo a pasta.")
            self.janela.abrir_pasta()
            return
        mpv = shutil.which("mpv")
        try:
            if mpv:
                subprocess.Popen(
                    [mpv, "--player-operation-mode=pseudo-gui", caminho],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(caminho).get_uri())
        except Exception as e:
            self.janela.toast(f"Não foi possível abrir: {e}")

    def _resolver_arquivo(self, item) -> str | None:
        """Resolve o caminho real do arquivo (cobre MP3 pós-conversão e paths órfãos)."""
        candidato = item.caminho_arquivo
        if candidato and os.path.isfile(candidato):
            return candidato

        pasta = item.caminho_arquivo and os.path.dirname(item.caminho_arquivo)
        if not pasta and self.config.pasta_destino:
            pasta = self.config.pasta_destino
        if not pasta or not os.path.isdir(pasta):
            return None

        base = item.titulo or ""
        if candidato:
            base = os.path.splitext(os.path.basename(candidato))[0]
        if base:
            for ext in (".mp3", ".mp4", ".mkv", ".webm", ".m4a", ".opus"):
                p = os.path.join(pasta, base + ext)
                if os.path.isfile(p):
                    return p

            chave = base.lower()
            for nome in os.listdir(pasta):
                if chave in nome.lower() and any(
                    nome.lower().endswith(e) for e in (".mp3", ".mp4", ".mkv", ".webm", ".m4a")
                ):
                    return os.path.join(pasta, nome)
        return None

    # ------------------------------------------------------------------
    def _mudou_formato(self, combo, _p) -> None:
        idx = combo.get_selected()
        if 0 <= idx < len(FORMATOS):
            self._formato_idx = idx
            self.config.formato_padrao = FORMATOS[idx].chave
            self.config.salvar()

    def _mudou_qualidade(self, combo, _p) -> None:
        idx = combo.get_selected()
        if 0 <= idx < len(QUALIDADES):
            self._qualidade_idx = idx
            self.config.qualidade_padrao = QUALIDADES[idx].chave
            self.config.salvar()

    # ------------------------------------------------------------------
    def _mensagem_sucesso(self, item) -> str:
        return f"Concluído: {item.titulo_exibicao[:70]}"

    def recap_preferencias(self) -> None:
        """Reaplica o que mudou no diálogo de preferências."""
        try:
            idx = [f.chave for f in FORMATOS].index(self.config.formato_padrao)
        except ValueError:
            idx = 0
        if idx != self._formato_idx:
            self.seletor_formato.set_selected(idx)

        try:
            qidx = [q.chave for q in QUALIDADES].index(self.config.qualidade_padrao)
        except ValueError:
            qidx = 0
        if qidx != self._qualidade_idx:
            self.seletor_qualidade.set_selected(qidx)

        self.atualizar_destino()
