# Conversor & Baixador

Duas ferramentas de desktop em Python + GTK4/Libadwaita, com interface em
português:

- **Conversor de Arquivos** — converte vídeo, áudio, imagem, PDF, documento e
  pacote. Usa `ffmpeg`, ImageMagick, poppler, Ghostscript, 7-Zip e Tesseract.
- **Baixador de Vid e Img** — baixa vídeos (yt-dlp) e galerias de imagem
  (gallery-dl), com fila, pausar/retomar, legendas e capa.

O site de download fica em [`site/`](site/) e é publicado na Vercel; o contador
de downloads é um número anônimo no Supabase (sem IP, sem cookie).

## Baixar

Baixe em **[Releases](https://github.com/davifelixcosta10-ux/conversor-e-baixador/releases/latest)**
ou direto:

| | Windows | Linux | Código |
|---|---|---|---|
| Conversor de Arquivos | [`instalar-windows.ps1`](https://github.com/davifelixcosta10-ux/conversor-e-baixador/releases/latest/download/instalar-windows.ps1) | [`conversor.zip`](https://github.com/davifelixcosta10-ux/conversor-e-baixador/releases/latest/download/conversor.zip) | [`conversor-fonte.zip`](https://github.com/davifelixcosta10-ux/conversor-e-baixador/releases/latest/download/conversor-fonte.zip) |
| Baixador de Vid e Img | [`instalar-windows.ps1`](https://github.com/davifelixcosta10-ux/conversor-e-baixador/releases/latest/download/instalar-windows.ps1) | [`baixador.zip`](https://github.com/davifelixcosta10-ux/conversor-e-baixador/releases/latest/download/baixador.zip) | [`baixador-fonte.zip`](https://github.com/davifelixcosta10-ux/conversor-e-baixador/releases/latest/download/baixador-fonte.zip) |

O site de download é <https://conversor-e-baixador.vercel.app>.

## Linux

```bash
unzip conversor.zip -d conversor && cd conversor
./instalar.sh          # instala em ~/.local/share/conversor + atalho no menu
conversor
```

Dependências (Arch / Debian):

```bash
sudo pacman -S python-gobject gtk4 libadwaita ffmpeg imagemagick \
               poppler ghostscript 7zip tesseract mpv
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 ffmpeg imagemagick \
                 poppler-utils ghostscript p7zip-full tesseract-ocr mpv
```

O instalador avisa o que estiver faltando; presets que dependem de um binário
ausente ficam escondidos na interface em vez de falharem.

## Windows

```powershell
powershell -ExecutionPolicy Bypass -File instalar-windows.ps1
```

O instalador:

1. instala o MSYS2 (via `winget`) se ainda não existir;
2. instala Python, PyGObject, GTK4, Libadwaita, ffmpeg, ImageMagick, poppler,
   Ghostscript, 7-Zip, Tesseract e mpv;
3. instala `yt-dlp` e `requests` no Python do MSYS2;
4. copia os apps para `%LOCALAPPDATA%\Programs` e cria atalhos no menu Iniciar
   e na área de trabalho.

Tudo por usuário — não precisa de administrador. PyGObject não tem rodas
oficiais no Windows, por isso o GTK vem do MSYS2: é a única forma de rodar
GTK4 + Python sem compilar nada.

Ferramentas: `-App conversor|baixador|ambos` (padrão `ambos`),
`-BaseUrl <url>` para baixar de outro lugar, `-PularDependencias` se o
ambiente já está pronto.

## Estrutura

```
apps/conversor/    conversor de arquivos (main.py + pacote conversor/)
apps/baixador/     baixador (main.py + pacote ytdlgtk/ + bin/yt-dlp vendido)
site/              site estático de download (HTML/CSS/JS, sem build)
.github/workflows/ build Windows (MSYS2) e checagem de sintaxe no CI
```

Código específico de sistema fica concentrado em
`apps/*/…/plataforma.py` (pastas do usuário, abrir arquivo, subprocessos,
fontes). O resto do código é igual nas três plataformas.

## Rodando do código

```bash
git clone https://github.com/davifelixcosta10-ux/conversor-e-baixador
cd conversor-e-baixador/apps/conversor && python3 main.py
cd ../baixador && python3 main.py    # usa bin/yt-dlp embutido
```

## Como testar

Não há suíte automatizada. O que dá para verificar rápido:

```bash
python3 -m py_compile apps/conversor/conversor/*.py apps/baixador/ytdlgtk/*.py
python3 apps/conversor/main.py     # janela abre, converte um arquivo de teste
python3 apps/baixador/main.py      # janela abre, baixa um vídeo curto
```

Conversões por categoria (todas validadas em Linux): vídeo (mp4/webm/mkv/gif/
webp animado), áudio (mp3/flac/ogg/m4a/wav), imagem (png/jpg/webp/avif/tiff/pdf),
documento (pdf→png/jpg/txt, dividir/juntar/comprimir, imagens→pdf, OCR) e
outros (zip/7z/extrair).

GIF e WebP animado são os únicos formatos com **loop infinito gravado** — o
mpv repete sozinho. MP4/WebM não carregam essa marcação.

## Licença

MIT — veja [LICENSE](LICENSE).

O site não hospeda conteúdo de terceiros. As ferramentas baixam da fonte, como
um navegador faria; use com responsabilidade e respeite os termos dos sites.
