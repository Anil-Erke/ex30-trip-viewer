"""Yolculuk kümesinden türetilen toplamlar.

Tanımlar araçtaki `trip/TripStats.kt` ve `trip/RangeAuditor.kt` ile aynı
tutuldu; aksi halde aynı veri için araçta başka, masaüstünde başka bir ortalama
görünürdü:

  * Ortalama tüketim **enerji ağırlıklı**: 2 km'lik yolculuk 200 km'likle aynı
    ağırlığa sahip olmamalı.
  * Menzil sapması **mesafe ağırlıklı** ve yalnızca ≥ 5 km yolculuklarda
    hesaplanıyor (RANGE_REMAINING 1 km adımlarla değişiyor).
  * Sıcaklık bantları: < 5, 5–15, 15–25, > 25 °C.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Sequence

from . import i18n
from .model import PerfRecord, Trip

#: Menzil sapmasının hesaplandığı en kısa mesafe (RangeAuditor.MIN_DISTANCE_KM).
MIN_BIAS_DISTANCE_KM = 5.0

#: Göstergenin "tuttu" sayıldığı bant (RangeAuditor.ACCURATE_BAND).
ACCURATE_BAND = 0.05

BANDS: tuple[tuple[str, float, float], ...] = (
    ("< 5 °C", float("-inf"), 5.0),
    ("5 – 15 °C", 5.0, 15.0),
    ("15 – 25 °C", 15.0, 25.0),
    ("> 25 °C", 25.0, float("inf")),
)


@dataclass(frozen=True)
class BandStat:
    label: str
    trip_count: int
    km: float
    consumption_kwh100: float | None


@dataclass(frozen=True)
class Summary:
    trip_count: int
    total_km: float
    #: Düzeltilmiş tekerlek mesafesi toplamı (model.WHEEL_TICK_SCALE ile).
    total_wheel_km: float | None
    total_duration_sec: int
    total_energy_kwh: float
    total_regen_kwh: float
    total_alt_gain_m: float
    avg_consumption_kwh100: float | None
    avg_range_bias: float | None
    avg_speed_kmh: float | None
    max_speed_kmh: float | None
    first_start: datetime | None
    last_start: datetime | None
    #: Tür başına en iyi A4 ölçümü (dört türde de küçük değer daha iyi).
    best_records: dict[str, PerfRecord]


def summarize(trips: Sequence[Trip]) -> Summary:
    km = 0.0
    wheel_km = 0.0
    wheel_seen = False
    duration = 0
    energy = 0.0
    measured_km = 0.0
    regen = 0.0
    alt_gain = 0.0
    max_speed: float | None = None
    bests: dict[str, PerfRecord] = {}

    for t in trips:
        km += t.distance_km
        duration += t.duration_sec
        alt_gain += t.alt_gain_m
        if t.wheel_distance_corrected_km is not None:
            wheel_km += t.wheel_distance_corrected_km
            wheel_seen = True
        if t.regen_kwh is not None:
            regen += t.regen_kwh
        if t.energy_kwh is not None and t.distance_km > 0:
            energy += t.energy_kwh
            measured_km += t.distance_km
        if t.max_speed_kmh is not None:
            max_speed = t.max_speed_kmh if max_speed is None else max(max_speed, t.max_speed_kmh)
        for r in t.records:
            current = bests.get(r.kind)
            if current is None or r.value < current.value:
                bests[r.kind] = r

    starts = [t.start_dt for t in trips]
    return Summary(
        trip_count=len(trips),
        total_km=km,
        total_wheel_km=wheel_km if wheel_seen else None,
        total_duration_sec=duration,
        total_energy_kwh=energy,
        total_regen_kwh=regen,
        total_alt_gain_m=alt_gain,
        avg_consumption_kwh100=(energy / measured_km * 100.0) if measured_km > 0 else None,
        avg_range_bias=average_range_bias(trips),
        # Toplam süre 0 olabiliyor (tek kayıtlık, saniyesi yuvarlanmış dosyalar).
        avg_speed_kmh=(km / (duration / 3600.0)) if duration > 0 else None,
        max_speed_kmh=max_speed,
        first_start=min(starts) if starts else None,
        last_start=max(starts) if starts else None,
        best_records=bests,
    )


def average_range_bias(trips: Iterable[Trip]) -> float | None:
    """Mesafe ağırlıklı ortalama menzil sapması (RangeAuditor.averageFactor)."""
    weighted = 0.0
    total_km = 0.0
    for t in trips:
        if t.range_bias_factor is None or t.distance_km <= 0:
            continue
        weighted += t.range_bias_factor * t.distance_km
        total_km += t.distance_km
    return weighted / total_km if total_km > 0 else None


@dataclass(frozen=True)
class RangeVerdict:
    """Gösterge kararı — RangeAuditor.Verdict'in karşılığı. Metin üretmiyor;
    insan diline çevirmek `bias_verdict`'in işi (araçtaki TripFormat gibi)."""

    factor: float
    #: "accurate" | "optimistic" | "pessimistic"
    kind: str
    #: 1,0'dan sapma, yüzde, işaretsiz.
    percent: float


def range_verdict(factor: float | None) -> RangeVerdict | None:
    if factor is None:
        return None
    deviation = factor - 1.0
    if abs(deviation) <= ACCURATE_BAND:
        kind = "accurate"
    elif deviation > 0:
        kind = "optimistic"
    else:
        kind = "pessimistic"
    return RangeVerdict(factor=factor, kind=kind, percent=abs(deviation) * 100.0)


def bias_verdict(factor: float | None) -> str:
    """Sapma kararını geçerli dile çevirir (TripFormat'ın masaüstü karşılığı)."""
    verdict = range_verdict(factor)
    if verdict is None:
        return "—"
    return i18n.t(
        f"bias.{verdict.kind}",
        factor=i18n.num(verdict.factor, 2),
        percent=i18n.pct(verdict.percent),
    )


def band_stats(trips: Sequence[Trip]) -> list[BandStat]:
    out: list[BandStat] = []
    for label, lo, hi in BANDS:
        count = 0
        km = 0.0
        energy = 0.0
        measured_km = 0.0
        for t in trips:
            temp = t.temp
            if temp is None or not (lo <= temp < hi):
                continue
            count += 1
            km += t.distance_km
            if t.energy_kwh is not None and t.distance_km > 0:
                energy += t.energy_kwh
                measured_km += t.distance_km
        out.append(
            BandStat(
                label=label,
                trip_count=count,
                km=km,
                consumption_kwh100=(energy / measured_km * 100.0) if measured_km > 0 else None,
            )
        )
    return out


@dataclass(frozen=True)
class DayStat:
    day: date
    trip_count: int
    km: float
    energy_kwh: float
    consumption_kwh100: float | None


def by_day(trips: Sequence[Trip]) -> list[DayStat]:
    """Günlük toplamlar, tarihe göre artan."""
    buckets: dict[date, list[Trip]] = {}
    for t in trips:
        buckets.setdefault(t.start_dt.date(), []).append(t)

    out: list[DayStat] = []
    for day in sorted(buckets):
        group = buckets[day]
        km = sum(t.distance_km for t in group)
        energy = 0.0
        measured_km = 0.0
        for t in group:
            if t.energy_kwh is not None and t.distance_km > 0:
                energy += t.energy_kwh
                measured_km += t.distance_km
        out.append(
            DayStat(
                day=day,
                trip_count=len(group),
                km=km,
                energy_kwh=energy,
                consumption_kwh100=(energy / measured_km * 100.0) if measured_km > 0 else None,
            )
        )
    return out


def duration_text(total_sec: int) -> str:
    """Toplam süre, saniyesiz (özet kartı)."""
    return i18n.duration(total_sec, seconds=False)
