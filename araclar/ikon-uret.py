"""Uygulama ikonunu üretir: assets/ex30.ico

Ayrı bir çizim programına bağımlı kalmamak için ikon koda gömüldü; renkler
arayüzün paletinden (`ex30trips/theme.py`) geliyor, böylece exe simgesi ile
pencere aynı görünüyor.

Çalıştırma:  py -3 araclar/ikon-uret.py
Bağımlılık:  Pillow (yoksa derleme betiği ikonsuz devam eder)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from ex30trips import theme  # noqa: E402

#: Windows'un ikondan beklediği boyutlar; hepsi tek .ico içine gömülüyor.
SIZES = (16, 24, 32, 48, 64, 128, 256)

OUTPUT = ROOT / "assets" / "ex30.ico"


def draw(size: int = 1024) -> Image.Image:
    """Ölçekten bağımsız çizim: her şey `size` oranıyla veriliyor."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    u = size / 100.0  # birim: yüzde

    # Zemin — arayüzün panel rengi, yuvarlatılmış kare.
    d.rounded_rectangle(
        (2 * u, 2 * u, 98 * u, 98 * u),
        radius=20 * u,
        fill=theme.PANEL,
        outline=theme.LINE,
        width=max(1, int(1.5 * u)),
    )

    # Yükselen üç bar: yolculuk başına mesafe.
    bars = ((20, 62), (38, 48), (56, 34))
    for x, top in bars:
        d.rounded_rectangle(
            (x * u, top * u, (x + 12) * u, 80 * u),
            radius=2.5 * u,
            fill=theme.ACCENT,
        )

    # Barların üstünden geçen eğilim çizgisi + son nokta: tüketim grafiği.
    points = [(18 * u, 70 * u), (44 * u, 40 * u), (62 * u, 46 * u), (84 * u, 22 * u)]
    d.line(points, fill=theme.ORANGE, width=max(2, int(4 * u)), joint="curve")
    r = 5 * u
    d.ellipse((84 * u - r, 22 * u - r, 84 * u + r, 22 * u + r), fill=theme.ORANGE)

    # Alt çizgi: eksen.
    d.line((16 * u, 84 * u, 84 * u, 84 * u), fill=theme.MUTED, width=max(1, int(1.5 * u)))
    return image


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    master = draw(1024)
    # Küçük boyutlar tek tek küçültülüyor: ICO'nun kendi ölçekleyicisi
    # 16 px'te ayrıntıyı eziyor, LANCZOS daha okunur bir simge veriyor.
    frames = [master.resize((s, s), Image.LANCZOS) for s in SIZES]
    frames[-1].save(OUTPUT, format="ICO", sizes=[(s, s) for s in SIZES], append_images=frames[:-1])
    print(f"ikon yazıldı: {OUTPUT}")

    preview = ROOT / "assets" / "ex30-256.png"
    master.resize((256, 256), Image.LANCZOS).save(preview)
    print(f"önizleme     : {preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
