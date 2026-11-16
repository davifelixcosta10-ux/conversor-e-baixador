<#
.SYNOPSIS
    Instalador do Conversor de Arquivos e do Baixador de Vid e Img no Windows.

.DESCRIPTION
    Instala GTK4 + Python pelo MSYS2 (uma vez), baixa o app, copia para
    %LOCALAPPDATA%\Programs e cria atalhos no menu Iniciar e na area de
    trabalho. Tudo por usuario -- nao precisa de administrador.

    Se o MSYS2 ja estiver instalado, ele e reaproveitado.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File instalar-windows.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File instalar-windows.ps1 -App conversor
#>

[CmdletBinding()]
param(
    [ValidateSet("ambos", "conversor", "baixador")]
    [string]$App = "ambos",

    # Onde estao conversor.zip / baixador.zip (troque se hospedar em outro lugar).
    [string]$BaseUrl = "https://github.com/davifelixcosta10-ux/conversor-e-baixador/releases/latest/download",

    # Pula a instalacao do MSYS2 quando o ambiente ja esta pronto.
    [switch]$PularDependencias
)

$ErrorActionPreference = "Stop"
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

$Msys = "C:\msys64"
$Bash = Join-Path $Msys "usr\bin\bash.exe"
$Py   = Join-Path $Msys "mingw64\bin\python.exe"
$Prog = Join-Path $env:LOCALAPPDATA "Programs"
$Temp = Join-Path $env:TEMP ("instalador-" + [guid]::NewGuid().ToString("N").Substring(0, 8))

function Passo($texto) { Write-Host "-> $texto" -ForegroundColor Cyan }
function Ok($texto)    { Write-Host "OK  $texto" -ForegroundColor Green }
function Aviso($texto) { Write-Host "!!  $texto" -ForegroundColor Yellow }
function Erro($texto)  { Write-Host "XX  $texto" -ForegroundColor Red }

# ---------------------------------------------------------------------------
# 1. MSYS2 + dependencias
# ---------------------------------------------------------------------------
function Instalar-Msys2 {
    if (Test-Path $Bash) {
        Ok "MSYS2 ja instalado em $Msys"
        return
    }

    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget nao encontrado. Instale o MSYS2 em https://www.msys2.org e rode este script de novo."
    }

    Passo "MSYS2 nao encontrado. Instalando pelo winget (pode demorar alguns minutos)..."
    winget install --id MSYS2.MSYS2 --accept-source-agreements --accept-package-agreements --silent

    if (-not (Test-Path $Bash)) {
        throw "O MSYS2 nao terminou de instalar. Rode o script de novo, ou instale manualmente por https://www.msys2.org"
    }
    Ok "MSYS2 instalado"
}

function Rodar-Bash($comando) {
    $env:MSYSTEM = "MINGW64"
    $env:CHERE_INVOKING = "1"
    & $Bash -lc $comando
    if ($LASTEXITCODE -ne 0) { throw "Falhou dentro do MSYS2: $comando" }
}

function Instalar-Dependencias {
    Passo "Atualizando o MSYS2 (chaves e pacotes base)..."
    Rodar-Bash "pacman -Sy --noconfirm --needed msys2-keyring"
    Rodar-Bash "pacman -Syu --noconfirm"

    $pacotes = @(
        "mingw-w64-x86_64-python",
        "mingw-w64-x86_64-python-pip",
        "mingw-w64-x86_64-python-gobject",
        "mingw-w64-x86_64-gtk4",
        "mingw-w64-x86_64-libadwaita",
        "mingw-w64-x86_64-adwaita-icon-theme",
        "mingw-w64-x86_64-hicolor-icon-theme",
        "mingw-w64-x86_64-ffmpeg",
        "mingw-w64-x86_64-imagemagick",
        "mingw-w64-x86_64-poppler",
        "mingw-w64-x86_64-ghostscript",
        "mingw-w64-x86_64-7zip",
        "mingw-w64-x86_64-tesseract",
        "mingw-w64-x86_64-mpv"
    )
    Passo "Instalando GTK4, Python e as ferramentas de conversao..."
    Rodar-Bash ("pacman -S --noconfirm --needed " + ($pacotes -join " "))

    Passo "Instalando yt-dlp e requests no Python do MSYS2..."
    Rodar-Bash "python -m pip install --upgrade --disable-pip-version-check yt-dlp requests"

    if (-not (Test-Path $Py)) { throw "Python do MSYS2 nao encontrado em $Py" }
    Ok "Dependencias prontas"
}

# ---------------------------------------------------------------------------
# 2. Lancadores e atalhos
# ---------------------------------------------------------------------------
function Novo-Lancador($destino, $nomeBat) {
    # .bat com o ambiente do GTK  +  .vbs que abre sem janela de console
    $bat = @'
@echo off
set "PATH={0}\mingw64\bin;%PATH%"
set "XDG_DATA_DIRS={0}\mingw64\share"
set "GSETTINGS_SCHEMA_DIR={0}\mingw64\share\glib-2.0\schemas"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
"{0}\mingw64\bin\python.exe" "%~dp0main.py" %*
'@ -f $Msys
    Set-Content -Path (Join-Path $destino ($nomeBat + ".bat")) -Value $bat -Encoding ASCII

    $vbs = @'
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "{0}"
sh.Run """{0}\{1}.bat""", 0, False
'@ -f $destino, $nomeBat
    Set-Content -Path (Join-Path $destino ($nomeBat + ".vbs")) -Value $vbs -Encoding ASCII

    return (Join-Path $destino ($nomeBat + ".vbs"))
}

function Novo-Atalho($vbs, $nome, $pasta) {
    if (-not (Test-Path $pasta)) { New-Item -ItemType Directory -Path $pasta -Force | Out-Null }
    $lnk = Join-Path $pasta ($nome + ".lnk")
    $shell = New-Object -ComObject WScript.Shell
    $atalho = $shell.CreateShortcut($lnk)
    $atalho.TargetPath = (Join-Path $env:SystemRoot "System32\wscript.exe")
    $atalho.Arguments = '"' + $vbs + '"'
    $atalho.WorkingDirectory = Split-Path $vbs
    $atalho.IconLocation = "$Py,0"
    $atalho.Description = $nome
    $atalho.Save()
    return $lnk
}

# ---------------------------------------------------------------------------
# 3. Instalacao de um app
# ---------------------------------------------------------------------------
function Instalar-App($id, $nome) {
    $zip = Join-Path $Temp ($id + ".zip")
    $url = $BaseUrl.TrimEnd("/") + "/" + $id + ".zip"

    Passo "Baixando $nome de $url"
    Invoke-WebRequest -Uri $url -OutFile $zip

    $destino = Join-Path $Prog (Get-Culture).TextInfo.ToTitleCase($id)
    if (Test-Path $destino) {
        Passo "Removendo instalacao anterior em $destino"
        Remove-Item $destino -Recurse -Force
    }
    New-Item -ItemType Directory -Path $destino -Force | Out-Null

    $extraido = Join-Path $Temp ($id + "-extraido")
    Expand-Archive -Path $zip -DestinationPath $extraido -Force
    Copy-Item -Path (Join-Path (Join-Path $extraido $id) "*") -Destination $destino -Recurse -Force

    # zipimport no Windows exige extensao .zip; o yt-dlp embutido nao tem.
    $vendor = Join-Path $destino "bin\yt-dlp"
    if (Test-Path $vendor) {
        Copy-Item $vendor (Join-Path $destino "bin\yt-dlp.zip") -Force
    }

    $vbs = Novo-Lancador $destino $id
    $menu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    Novo-Atalho $vbs $nome $menu | Out-Null
    $areaTrabalho = [Environment]::GetFolderPath("Desktop")
    if ($areaTrabalho) { Novo-Atalho $vbs $nome $areaTrabalho | Out-Null }

    Ok "$nome instalado em $destino"
}

# ---------------------------------------------------------------------------
# 4. Principal
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host " Conversor & Baixador -- instalador para Windows" -ForegroundColor Magenta
Write-Host ""

try {
    if ($PularDependencias) {
        if (-not (Test-Path $Py)) {
            throw "Python do MSYS2 nao encontrado. Rode sem -PularDependencias."
        }
    } else {
        Instalar-Msys2
        Instalar-Dependencias
    }

    New-Item -ItemType Directory -Path $Temp -Force | Out-Null

    if ($App -eq "ambos" -or $App -eq "conversor") {
        Instalar-App "conversor" "Conversor de Arquivos"
    }
    if ($App -eq "ambos" -or $App -eq "baixador") {
        Instalar-App "baixador" "Baixador de Vid e Img"
    }

    Write-Host ""
    Ok "Tudo pronto. Abra pelo menu Iniciar ou pelo atalho na area de trabalho."
    Write-Host ""
    Write-Host "  Desinstalar: apague as pastas em $Prog" -ForegroundColor DarkGray
    Write-Host "               e os atalhos correspondentes." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  Se o app nao abrir, rode o .bat da pasta de instalacao:" -ForegroundColor DarkGray
    Write-Host "  ele mostra o erro no console." -ForegroundColor DarkGray
    Write-Host ""
} catch {
    Write-Host ""
    Erro $_.Exception.Message
    Write-Host ""
    Write-Host "  Se algo ficou pela metade, apague $Prog\Conversor e $Prog\Baixador" -ForegroundColor DarkGray
    Write-Host "  e rode este script de novo." -ForegroundColor DarkGray
    exit 1
} finally {
    if (Test-Path $Temp) { Remove-Item $Temp -Recurse -Force -ErrorAction SilentlyContinue }
}
