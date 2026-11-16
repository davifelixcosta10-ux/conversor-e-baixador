#!/usr/bin/env bash
# Instalador do Conversor de Arquivos (Linux, por usuário — sem sudo).
set -euo pipefail

origem="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dados="${XDG_DATA_HOME:-$HOME/.local/share}/conversor"
atalhos="$HOME/.local/bin"
apps="$HOME/.local/share/applications"
icones="$HOME/.local/share/icons/hicolor/scalable/apps"

echo "→ instalando em $dados"
mkdir -p "$dados" "$atalhos" "$apps" "$icones"
cp -r "$origem"/. "$dados"/

cat > "$atalhos/conversor" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$dados:\${PYTHONPATH:-}"
exec python3 "$dados/main.py" "\$@"
EOF
chmod +x "$atalhos/conversor"

if [ -f "$dados/conversor/data/conversor.svg" ]; then
  cp "$dados/conversor/data/conversor.svg" "$icones/conversor.svg"
fi

cat > "$apps/conversor.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Conversor de Arquivos
GenericName=Conversor de mídia
Comment=Converta vídeo, áudio, imagem, PDF e documentos
Exec=$atalhos/conversor %F
Icon=conversor
Terminal=false
Categories=AudioVideo;
MimeType=video/mp4;video/webm;video/x-matroska;audio/mpeg;audio/flac;audio/ogg;image/jpeg;image/png;image/webp;image/avif;image/tiff;application/pdf;application/zip;application/x-7z-compressed;application/epub+zip;
Keywords=converter;video;audio;image;pdf;documento;ffmpeg;
StartupNotify=true
StartupWMClass=io.github.omarchy.Conversor
EOF

update-desktop-database "$apps" 2>/dev/null || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo
echo "✔ Conversor instalado. Rode: conversor"
echo "  (ou abra pelo menu de aplicativos: «Conversor de Arquivos»)"
echo
faltando=""
for bin in ffmpeg ffprobe magick; do
  command -v "$bin" >/dev/null 2>&1 || faltando="$faltando $bin"
done
if [ -n "$faltando" ]; then
  echo "⚠ Faltam ferramentas essenciais:$faltando"
  echo "  Arch:   sudo pacman -S ffmpeg imagemagick"
  echo "  Debian: sudo apt install ffmpeg imagemagick"
fi
for bin in pdftoppm pdftotext qpdf gs 7z tesseract; do
  command -v "$bin" >/dev/null 2>&1 || echo "· opcional ausente: $bin (as conversões que usam ele ficam escondidas)"
done
