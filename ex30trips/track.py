"""Yolculuğun GPS izi — Drive protokol 2, `trip-<startEpoch>.csv.gz` (PROTOKOL.md §3.2).

Biçim:

    # ex30-track;1;1790602585477
    t;lat;lon;alt;hacc;vacc;gps_kmh;kmh;kw;soc;dist_m
    1790602587240;41.000000;29.000000;100.0;5.0;0.5;;0.0;0.00;61.00;0.0

  * İlk satır sürüm ve `startEpoch`. **Bilinmeyen sürüm okunmaz**, kullanıcıya
    söylenir: yeni bir sürümde bir sütunun anlamı değişmiş olabilir, sessizce
    yanlış çizmek hatadan kötü.
  * **Sütunlar adla okunur, sırayla değil** — araç ileride sütun ekleyebilir
    ya da sırayı değiştirebilir.
  * Ayraç `;`, ondalık ayracı her zaman nokta. Boş alan = değer yoktu; None
    kalır, sıfıra çevrilmez (aracın vermediği değer uydurulmaz).
  * `kw` pozitif = tüketim, negatif = rejen. `alt` HAM GPS irtifası.

Araçtaki üretici: `trip/TrackRecorder.kt`. Bu modül de Tkinter bilmiyor.
Burada da çeviri her zaman `i18n.t(...)`: sütunlardan birinin adı `t`.
"""

from __future__ import annotations

import csv
import gzip
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO, Sequence

import numpy as np

from . import i18n

#: Okuyabildiğimiz biçim sürümleri.
FORMAT_VERSIONS = frozenset({1})

#: İlk satırın başı.
MAGIC = "# ex30-track"

#: Bilinen sütunlar. Dosyada olmayan sütun "hep boş" sayılır.
COLUMNS = ("t", "lat", "lon", "alt", "hacc", "vacc", "gps_kmh", "kmh", "kw", "soc", "dist_m")

#: Ortalama yer yarıçapı (m) — `dist_m` yoksa konumlardan mesafe için.
EARTH_RADIUS_M = 6_371_008.8

Value = float | None


class TrackError(Exception):
    """İz okunamadı. Sebep dil anahtarıyla taşınıyor, metne `str()` anında çevriliyor."""

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params

    def __str__(self) -> str:
        return i18n.t(self.key, **self.params)


@dataclass(frozen=True)
class Track:
    version: int
    start_epoch: int
    #: Sütun adı → değerler (satır sırasıyla). Bilinmeyen sütunlar da duruyor.
    columns: dict[str, tuple[Value, ...]]
    rows: int

    def get(self, name: str) -> tuple[Value, ...]:
        """Sütunun değerleri; dosyada yoksa hepsi None."""
        values = self.columns.get(name)
        return values if values is not None else (None,) * self.rows

    def array(self, name: str) -> np.ndarray:
        """Sütun, eksik değerler NaN — matplotlib NaN'ı çizmiyor, boşluk bırakıyor."""
        return np.array([np.nan if v is None else v for v in self.get(name)], dtype=float)

    def has(self, name: str) -> bool:
        return any(v is not None for v in self.get(name))

    @property
    def has_position(self) -> bool:
        lat, lon = self.get("lat"), self.get("lon")
        return sum(1 for a, b in zip(lat, lon) if a is not None and b is not None) >= 2

    def distance_m(self) -> np.ndarray:
        """Mesafe ekseni: aracın `dist_m`'si, yoksa konumlardan toplanan mesafe.

        `dist_m` aracın hesabı ve özet mesafesiyle aynı kaynaktan geliyor, o
        yüzden tercih ediliyor. Konumdan hesap yalnızca o sütun hiç yoksa.
        """
        if self.has("dist_m"):
            return self.array("dist_m")
        return _haversine_cumulative(self.array("lat"), self.array("lon"))

    def speed_kmh(self) -> np.ndarray:
        """Aracın gösterge hızı; hiç yoksa GPS hızı."""
        return self.array("kmh") if self.has("kmh") else self.array("gps_kmh")

    @property
    def start_dt(self) -> datetime:
        return datetime.fromtimestamp(self.start_epoch / 1000.0)


def _haversine_cumulative(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    out = np.full(lat.shape, np.nan)
    total = 0.0
    prev: tuple[float, float] | None = None
    for i, (a, b) in enumerate(zip(lat, lon)):
        if math.isnan(a) or math.isnan(b):
            continue
        if prev is not None:
            p1, p2 = math.radians(prev[0]), math.radians(a)
            dp = p2 - p1
            dl = math.radians(b - prev[1])
            h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
            total += 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))
        out[i] = total
        prev = (a, b)
    return out


def _value(text: str) -> Value:
    text = text.strip()
    if not text:
        return None
    try:
        v = float(text)
    except ValueError:
        # Tek bozuk hücre bütün izi düşürmesin; o değer yokmuş gibi.
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def parse(text: str, expected_epoch: int | None = None) -> Track:
    """İz metnini ayrıştırır. `expected_epoch` verilirse başlıktakiyle tutmalı."""
    lines = [line.rstrip("\r") for line in text.split("\n")]
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines or not lines[0].startswith(MAGIC + ";"):
        raise TrackError("track.err.header")

    parts = lines[0][1:].strip().split(";")
    try:
        version = int(parts[1])
        start_epoch = int(parts[2])
    except (IndexError, ValueError):
        raise TrackError("track.err.header") from None
    if version not in FORMAT_VERSIONS:
        raise TrackError("track.err.version", version=version)
    if expected_epoch is not None and start_epoch != expected_epoch:
        raise TrackError("track.err.epoch", found=start_epoch, expected=expected_epoch)

    if len(lines) < 2 or not lines[1].strip():
        raise TrackError("track.err.columns")
    names = [n.strip() for n in lines[1].split(";")]

    data: dict[str, list[Value]] = {name: [] for name in names if name}
    rows = 0
    for line in lines[2:]:
        if not line.strip():
            continue
        cells = line.split(";")
        for i, name in enumerate(names):
            if name:
                data[name].append(_value(cells[i]) if i < len(cells) else None)
        rows += 1

    return Track(
        version=version,
        start_epoch=start_epoch,
        columns={name: tuple(values) for name, values in data.items()},
        rows=rows,
    )


def read(path: Path, expected_epoch: int | None = None) -> Track:
    """Diskteki izi okur; `.gz` ise açar."""
    raw = path.read_bytes()
    if path.suffix == ".gz":
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError) as e:
            raise TrackError("track.err.gzip", error=e) from e
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise TrackError("track.err.encoding") from e
    return parse(text, expected_epoch)


# --- CSV dışa aktarımı ----------------------------------------------------------

#: (sütun, başlık anahtarı, ondalık) — `None` ondalık = zaman sütunu.
EXPORT: tuple[tuple[str, str, int | None], ...] = (
    ("t", "csv.track.time", None),
    ("lat", "csv.track.lat", 6),
    ("lon", "csv.track.lon", 6),
    ("alt", "csv.track.alt", 1),
    ("hacc", "csv.track.hacc", 1),
    ("vacc", "csv.track.vacc", 1),
    ("gps_kmh", "csv.track.gps_kmh", 1),
    ("kmh", "csv.track.kmh", 1),
    ("kw", "csv.track.kw", 2),
    ("soc", "csv.track.soc", 2),
    ("dist_m", "csv.track.dist_m", 1),
)


def csv_header() -> list[str]:
    return [i18n.t(key) for _name, key, _decimals in EXPORT]


def csv_rows(track: Track) -> list[list[str]]:
    """Dışa aktarım satırları — tablo CSV'siyle aynı kurallar (i18n.csv_*):
    Türkçede ondalık virgül ve gün.ay.yıl, İngilizcede nokta ve ISO tarih.
    Boş değer boş hücre, sıfır değil."""
    cols: list[Sequence[Value]] = [track.get(name) for name, _key, _decimals in EXPORT]
    out: list[list[str]] = []
    for i in range(track.rows):
        row: list[str] = []
        for (name, _key, decimals), values in zip(EXPORT, cols):
            value = values[i]
            if decimals is None:
                row.append(
                    "" if value is None else i18n.csv_datetime(datetime.fromtimestamp(value / 1000.0))
                )
            else:
                row.append(i18n.csv_number(value, decimals))
        out.append(row)
    return out


def write_csv(track: Track, fh: IO[str]) -> None:
    """Çağıran `newline=""` ve `utf-8-sig` ile açmalı (Excel BOM'la tanıyor)."""
    writer = csv.writer(fh, delimiter=i18n.csv_delimiter())
    writer.writerow(csv_header())
    writer.writerows(csv_rows(track))
