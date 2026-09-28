"""Derleme öncesi ortam raporu — `exe-olustur.ps1` bunu okuyup karar veriyor.

Çıktı satırları `anahtar=değer`; eksik olan boş döner. Paketleri içe aktarmayı
denemiyoruz, yalnızca `find_spec` ile arıyoruz: eksik bir paket yüzünden
traceback basılırsa PowerShell onu hata sanıp derlemeyi düşürüyor.
"""

from __future__ import annotations

import importlib.metadata as metadata
import importlib.util as util
import sys


def spec_var(module: str) -> bool:
    try:
        return util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def surum(module: str, dist: str) -> str:
    """Modül kuruluysa sürümü, değilse boş dize."""
    if not spec_var(module):
        return ""
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return "?"


def main() -> int:
    print(f"python={sys.version.split()[0]}")
    print(f"executable={sys.executable}")
    print(f"tkinter={'1' if spec_var('tkinter') else ''}")
    print(f"matplotlib={surum('matplotlib', 'matplotlib')}")
    print(f"pyinstaller={surum('PyInstaller', 'pyinstaller')}")
    print(f"pillow={surum('PIL', 'pillow')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
