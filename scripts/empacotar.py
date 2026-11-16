#!/usr/bin/env python3
"""Gera os pacotes de download em site/downloads/.

Uso: python3 scripts/empacotar.py
"""

from __future__ import annotations

import pathlib
import zipfile

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "site" / "downloads"
IGNORAR_DIR = {"__pycache__", ".git", "dist", "build"}
IGNORAR_EXT = {".pyc", ".pyo"}


def arquivos(app: str, com_instalador: bool = True, com_bin: bool = True):
    base = RAIZ / "apps" / app
    for caminho in sorted(base.rglob("*")):
        rel = caminho.relative_to(base)
        if any(parte in IGNORAR_DIR for parte in rel.parts):
            continue
        if caminho.suffix in IGNORAR_EXT:
            continue
        if not com_instalador and caminho.name == "instalar.sh":
            continue
        if not com_bin and rel.parts and rel.parts[0] == "bin":
            continue
        if caminho.is_file():
            yield caminho, rel


def empacotar(app: str, sufixo: str, com_instalador: bool, com_bin: bool) -> pathlib.Path:
    destino = SAIDA / f"{app}{sufixo}.zip"
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for caminho, rel in arquivos(app, com_instalador, com_bin):
            z.write(caminho, arcname=f"{app}/{rel.as_posix()}")
    return destino


def main() -> int:
    SAIDA.mkdir(parents=True, exist_ok=True)
    for app in ("conversor", "baixador"):
        for sufixo, instalador, binario in (("", True, True), ("-fonte", False, False)):
            pacote = empacotar(app, sufixo, instalador, binario)
            print(f"{pacote.name:26s} {pacote.stat().st_size / 1024 / 1024:5.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
