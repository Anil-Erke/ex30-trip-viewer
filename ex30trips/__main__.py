"""Giriş noktası: `python -m ex30trips [--lang tr|en] [dosya|klasör ...]`.

Dil ilk iş olarak belirleniyor — eksik bağımlılık uyarısı bile seçilen dilde
çıksın. Öncelik: `--lang` > kayıtlı seçim (Dil menüsü) > Windows arayüz dili.
`--lang` yalnızca o açılış için geçerli, kayıtlı seçimi değiştirmiyor.

Eksik bağımlılık konsola değil pencereye yazılıyor: uygulama çift tıklamayla
(pythonw / .bat) açıldığında konsol görünmüyor ve hata sessizce kayboluyor.
"""

from __future__ import annotations

import sys

from . import i18n, settings


def split_language(argv: list[str]) -> tuple[str | None, list[str]]:
    """`--lang en` ya da `--lang=en` seçeneğini ayıklar; kalanlar dosya yolları."""
    language: str | None = None
    rest: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--lang" and i + 1 < len(argv):
            language = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--lang="):
            language = arg.split("=", 1)[1]
        else:
            rest.append(arg)
        i += 1
    return language, rest


def _missing_dependency(name: str, detail: str) -> int:
    message = i18n.t("startup.missing", name=name, detail=detail)
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(i18n.t("app.title"), message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)
    return 1


def main() -> int:
    language, rest = split_language(sys.argv[1:])
    i18n.set_language(i18n.resolve(cli=language, saved=settings.load().get("language")))

    try:
        import matplotlib  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as e:
        return _missing_dependency("matplotlib", str(e))

    from .app import main as run

    return run(rest)


if __name__ == "__main__":
    raise SystemExit(main())
