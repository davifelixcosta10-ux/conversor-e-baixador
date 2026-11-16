#!/usr/bin/env python3
"""Ponto de entrada do Conversor de Arquivos."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from conversor.app import principal

if __name__ == "__main__":
    sys.exit(principal())
