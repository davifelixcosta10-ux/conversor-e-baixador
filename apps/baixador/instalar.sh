#!/usr/bin/env bash
# Instalador do Baixador de Vid e Img (Linux, por usuário — sem sudo).
set -euo pipefail

origem="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dados="${XDG_DATA_HOME:-$HOME/.local/share}/baixador-videos"
atalhos="$HOME/.local/bin"
apps="$HOME/.local/share/applications"
icones="$HOME/.local/share/icons/hicolor/scalable/apps"

echo "→ instalando em $dados"
mkdir -p "$dados" "$atalhos" "$apps" "$icones"
cp -r "$origem"/. "$dados"/

cat > "$atalhos/baixador-videos" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$dados:\${PYTHONPATH:-}"
exec python3 "$dados/main.py" "\$@"
EOF
chmod +x "$atalhos/baixador-videos"

if [ -f "$dados/ytdlgtk/data/io.github.omarchy.YtdlGtk.svg" ]; then
  cp "$dados/ytdlgtk/data/io.github.omarchy.YtdlGtk.svg" "$icones/io.github.omarchy.YtdlGtk.svg"
fi

cat > "$apps/io.github.omarchy.YtdlGtk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Baixador de Vid e Img
GenericName=Baixador de vídeos e imagens
Comment=Baixe vídeos e galerias de imagem de qualquer site
Exec=$atalhos/baixador-videos %U
Icon=io.github.omarchy.YtdlGtk
Terminal=false
Categories=Network;AudioVideo;
MimeType=x-scheme-handler/http;x-scheme-handler/https;
Keywords=baixar;download;video;imagem;yt-dlp;gallery-dl;
StartupNotify=true
StartupWMClass=io.github.omarchy.YtdlGtk
EOF

update-desktop-database "$apps" 2>/dev/null || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo
echo "✔ Baixador instalado. Rode: baixador-videos"
echo "  (ou abra pelo menu de aplicativos: «Baixador de Vid e Img»)"
echo
command -v ffmpeg >/dev/null 2>&1 || echo "⚠ ffmpeg não encontrado — necessário para juntar vídeo+áudio (sudo pacman -S ffmpeg)"
command -v mpv >/dev/null 2>&1 || echo "· mpv não encontrado — só o botão «Abrir» deixa de funcionar"
