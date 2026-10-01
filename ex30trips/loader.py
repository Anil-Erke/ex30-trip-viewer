"""Dışa aktarılmış yolculuk dosyalarını okuma ve birleştirme.

Araçtan çıkan dosya, EX30 Telemetry / EX30 Yol Analizi'nin `trips.json`
içeriğidir; dışa aktarımda adı `trips-<damga>.txt` olur (DataExporter). İçerik
her iki halde de aynı: yolculuk nesnelerinden oluşan bir JSON dizisi.

Drive'da (protokol 2 ve 3) her yolculuğun özeti ayrı dosya (`trip-<startEpoch>.json`):
aynı biçimde TEK bir yolculuk nesnesi, dizi değil. Drive önbelleği bu
dosyalardan oluşan bir klasör; klasör taraması onları da buluyor.

Aynı yolculuk birden çok dışa aktarımda bulunur — dosyalar birleştirilirken
`startEpoch` anahtarıyla teklenir, alanı daha dolu olan kopya kazanır.

Kaynaklar birikir: Drive'dan inen son 10 günün üstüne bir klasör açıldığında
ikisi birden gösterilir. Her yükleme bir `Source` olarak saklanıyor, ekrandaki
liste `combine()` ile hepsinin birleşimi. Böylece tek bir kaynak kaldırılınca
geri kalanlar yeniden okunmadan yerinde kalıyor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from . import i18n
from .model import Trip

#: Klasör tarandığında bakılan desenler. `trip-*.json` Drive'daki yolculuk özeti.
PATTERNS = ("trips*.json", "trips*.txt", "trip-*.json")


class TripFileError(Exception):
    """Dosya okunamadı ya da içinde yolculuk yok.

    Sebep dil anahtarıyla taşınıyor, metne `str()` anında çevriliyor: ekrana
    hangi dil açıkken basılırsa o dilde çıkar.
    """

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params

    def __str__(self) -> str:
        return i18n.t(self.key, **self.params)


@dataclass(frozen=True)
class LoadResult:
    trips: list[Trip]
    files: list[Path]
    #: (dosya, sebep) — okunamayan dosyalar; yükleme bunlar yüzünden durmaz.
    failures: list[tuple[Path, str]]
    #: Birleştirmede elenen yinelenen kayıt sayısı.
    duplicates: int


@dataclass(frozen=True)
class Source:
    """Ekrana veri veren tek bir kaynak: dosya seçimi, klasör ya da Drive.

    `paths` yeniden okumak için duruyor (F5): klasör kaynağında araya yeni bir
    dışa aktarım düştüyse yenileme onu da alsın diye yol saklanıyor, dosya
    listesi değil.
    """

    kind: str
    label: str
    paths: tuple[Path, ...]
    result: LoadResult

    @property
    def key(self) -> tuple[str, ...]:
        """Kaynak kimliği: aynı yol ikinci kez seçilince kopya kaynak açılmasın.

        Sıralı, çünkü çoklu seçimde dosyaların geliş sırası aynı seçim için bile
        değişebiliyor.
        """
        return tuple(sorted(str(p) for p in self.paths))


def combine(sources: Iterable[Source]) -> LoadResult:
    """Yüklü bütün kaynakları tek bir sonuçta toplar.

    Kaynakların kendi içindeki tekleme zaten yapılmış; buradaki sayım kaynaklar
    ARASINDA elenenleri ekliyor — "Drive'da da klasörde de duran 40 yolculuk"
    kullanıcıya bir kez sayılmalı.
    """
    sources = list(sources)
    trips, across = merge(s.result.trips for s in sources)
    return LoadResult(
        trips=trips,
        files=[f for s in sources for f in s.result.files],
        failures=[x for s in sources for x in s.result.failures],
        duplicates=across + sum(s.result.duplicates for s in sources),
    )


def _extract(payload: object) -> list[dict]:
    """JSON gövdesinden yolculuk nesnelerini çıkarır.

    Dizi (`trips.json`) ya da tek yolculuk nesnesi (Drive özeti) olabilir;
    ileride sarmalayıcı bir nesne ({"trips": [...]}) gelirse diye o biçim de
    kabul ediliyor. Tek nesne `startEpoch`'undan tanınıyor ve bu denetim
    sarmalayıcıdan ÖNCE: özetin kendi `records` alanı (performans ölçümleri)
    yolculuk listesi sanılırsa özet sessizce kaybolurdu.
    """
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and "startEpoch" in payload:
        items = [payload]
    elif isinstance(payload, dict):
        items = payload.get("trips") or payload.get("records") or []
    else:
        items = []
    return [o for o in items if isinstance(o, dict)]


def read_file(path: Path) -> list[Trip]:
    """Tek dosyayı okur. Okunamayan tek kayıt bütün dosyayı düşürmez."""
    raw = path.read_text(encoding="utf-8-sig").strip()
    if not raw:
        raise TripFileError("file.empty")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise TripFileError("file.bad_json", line=e.lineno) from e

    objects = _extract(payload)
    if not objects:
        raise TripFileError("file.no_trips")

    trips: list[Trip] = []
    for o in objects:
        try:
            trip = Trip.from_json(o, source=path.name)
        except (TypeError, ValueError):
            continue
        if trip.start_epoch > 0:
            trips.append(trip)
    if not trips:
        raise TripFileError("file.unreadable")
    return trips


def merge(groups: Iterable[Sequence[Trip]]) -> tuple[list[Trip], int]:
    """Birden çok dosyanın kayıtlarını tekleyerek birleştirir.

    Aynı `startEpoch` iki dosyada da varsa alanı daha dolu olanı tutar: eski
    dışa aktarım şema 2, yenisi şema 3 olabilir.
    """
    best: dict[int, Trip] = {}
    duplicates = 0
    for group in groups:
        for trip in group:
            current = best.get(trip.start_epoch)
            if current is None:
                best[trip.start_epoch] = trip
                continue
            duplicates += 1
            if (trip.schema_version, trip.field_count()) > (
                current.schema_version,
                current.field_count(),
            ):
                best[trip.start_epoch] = trip
    trips = sorted(best.values(), key=lambda t: t.start_epoch)
    return trips, duplicates


def load(paths: Iterable[Path]) -> LoadResult:
    """Dosya ve/veya klasör yollarını okur, birleştirir.

    Klasör verilirse içindeki `trips*` dosyaları taranır (alt klasörler dahil).
    """
    files: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            found: set[Path] = set()
            for pattern in PATTERNS:
                found.update(path.rglob(pattern))
            files.extend(sorted(found))
        elif path.exists():
            files.append(path)

    groups: list[list[Trip]] = []
    ok_files: list[Path] = []
    failures: list[tuple[Path, str]] = []
    for f in files:
        try:
            groups.append(read_file(f))
            ok_files.append(f)
        except (TripFileError, OSError, UnicodeDecodeError) as e:
            failures.append((f, str(e)))

    trips, duplicates = merge(groups)
    return LoadResult(trips=trips, files=ok_files, failures=failures, duplicates=duplicates)
