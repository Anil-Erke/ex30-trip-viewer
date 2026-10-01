"""Araçtan çıkan yolculuk kaydının Python karşılığı.

Alan adları ve birimler EX30 Telemetry'deki `trip/Trip.kt` ile birebir aynı.
Burada yalnızca hesaba giren kuralları tekrar ediyoruz:

  * `energy_kwh` **net** tüketimdir (tüketilen − geri kazanılan) — EnergyAccountant.
  * `regen_kwh` pozitiftir; brüt tüketim = net + rejen.
  * `range_bias_factor` = (gösterge menzil düşüşü) ÷ (gidilen km).
    1,0 = gösterge tuttu, 1,0 üstü **iyimser**, altı **kötümser** — RangeAuditor.
  * `wheel_distance_km` tekerlek tiklerinden gelen **HAM** mesafedir; gösterirken
    ve GPS ile kıyaslarken `WHEEL_TICK_SCALE` ile çarpılır
    (`wheel_distance_corrected_km`) — araçtaki TripAccumulator ve Mobile ile aynı.
  * Null alan normaldir: araç o property'yi vermediyse değer yazılmamıştır.
    Uydurma sıfır üretmiyoruz; grafikte o nokta hiç çizilmez.

Şema 1 ve 2'den gelen eski kayıtlar da okunur: eksik alanlar None kalır.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping

from . import i18n

#: Tekerlek tiklerinden gelen mesafenin ölçeği — araçtaki
#: `Constants.WHEEL_TICK_SCALE` ve EX30 Trip Mobile'daki ile aynı değer.
#: Kayıttaki `wheelDistanceKm` HAM saklanıyor, çarpan kayda gömülmüyor:
#: sabit değişirse bütün geçmiş yeniden türetilebilsin. Değiştirilecekse
#: üç uygulamada birlikte değişmeli.
WHEEL_TICK_SCALE = 1.02536


def _opt_float(o: Mapping[str, Any], key: str) -> float | None:
    """JSON'da alan yoksa, null ise ya da sayı değilse None döndürür."""
    if key not in o or o[key] is None:
        return None
    try:
        v = float(o[key])
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def _req_float(o: Mapping[str, Any], key: str) -> float:
    return _opt_float(o, key) or 0.0


@dataclass(frozen=True)
class PerfRecord:
    """A4 performans ölçümü. Birim türe göre değişir: saniye ya da metre."""

    kind: str
    value: float
    unit: str
    epoch: int

    @property
    def label(self) -> str:
        """Ölçüm türünün adı (lang: perf.<tür>); tanınmayan tür olduğu gibi."""
        key = f"perf.{self.kind}"
        return i18n.t(key) if i18n.has(key) else self.kind

    @property
    def when(self) -> datetime:
        return datetime.fromtimestamp(self.epoch / 1000.0)

    def pretty(self) -> str:
        decimals = 1 if self.unit == "m" else 2
        return f"{i18n.num(self.value, decimals)} {self.unit}"

    @staticmethod
    def from_json(o: Mapping[str, Any]) -> "PerfRecord":
        # Şema 1 uyumluluğu: `value` yoksa `seconds` alanından oku.
        value = _opt_float(o, "value")
        if value is None:
            value = _opt_float(o, "seconds") or 0.0
        return PerfRecord(
            kind=str(o.get("kind", "")),
            value=value,
            unit=str(o.get("unit", "s")),
            epoch=int(o.get("epoch", 0) or 0),
        )


@dataclass(frozen=True)
class Trip:
    """Kapanmış bir yolculuk."""

    start_epoch: int
    end_epoch: int
    duration_sec: int
    distance_km: float
    energy_kwh: float | None = None
    regen_kwh: float | None = None
    soc_start: float | None = None
    soc_end: float | None = None
    range_start: float | None = None
    range_end: float | None = None
    avg_speed_kmh: float | None = None
    max_speed_kmh: float | None = None
    temp_start: float | None = None
    temp_avg: float | None = None
    alt_gain_m: float = 0.0
    alt_loss_m: float = 0.0
    potential_kwh: float | None = None
    consumption_kwh100: float | None = None
    range_bias_factor: float | None = None
    wheel_distance_km: float | None = None
    records: tuple[PerfRecord, ...] = ()
    schema_version: int = 1
    #: Kaydın geldiği dosya — birden çok dışa aktarım birleştirildiğinde lazım.
    source: str = ""

    # --- Türetilmiş değerler -------------------------------------------------

    @property
    def start_dt(self) -> datetime:
        return datetime.fromtimestamp(self.start_epoch / 1000.0)

    @property
    def end_dt(self) -> datetime:
        return datetime.fromtimestamp(self.end_epoch / 1000.0)

    @property
    def duration(self) -> timedelta:
        return timedelta(seconds=self.duration_sec)

    @property
    def soc_drop(self) -> float | None:
        if self.soc_start is None or self.soc_end is None:
            return None
        return self.soc_start - self.soc_end

    @property
    def range_drop(self) -> float | None:
        if self.range_start is None or self.range_end is None:
            return None
        return self.range_start - self.range_end

    @property
    def gross_kwh(self) -> float | None:
        """Brüt tüketim: net + rejen. İkisi de yoksa None."""
        if self.energy_kwh is None or self.regen_kwh is None:
            return None
        return self.energy_kwh + self.regen_kwh

    @property
    def regen_share(self) -> float | None:
        """Brüt tüketimin yüzde kaçı rejenle geri geldi."""
        gross = self.gross_kwh
        if gross is None or gross <= 0:
            return None
        return (self.regen_kwh or 0.0) / gross * 100.0

    @property
    def consumption(self) -> float | None:
        """kWh/100 km. Kayıtta yoksa net enerjiden hesaplanır."""
        if self.consumption_kwh100 is not None:
            return self.consumption_kwh100
        if self.energy_kwh is not None and self.distance_km > 0:
            return self.energy_kwh / self.distance_km * 100.0
        return None

    @property
    def temp(self) -> float | None:
        """Yolculuğun temsili dış sıcaklığı: ortalama, yoksa başlangıç."""
        return self.temp_avg if self.temp_avg is not None else self.temp_start

    @property
    def net_alt_m(self) -> float:
        return self.alt_gain_m - self.alt_loss_m

    @property
    def wheel_distance_corrected_km(self) -> float | None:
        """Tekerlek mesafesi, ölçek düzeltmesiyle — gösterilen ve kıyaslanan değer."""
        if self.wheel_distance_km is None:
            return None
        return self.wheel_distance_km * WHEEL_TICK_SCALE

    @property
    def gps_wheel_ratio(self) -> float | None:
        """GPS mesafesi ÷ **düzeltilmiş** tekerlek mesafesi. 1,0'dan sapma GPS hatasıdır.

        Bölen ham değer olsaydı oran sistematik olarak ~%2,5 yüksek çıkardı
        (araç ve Mobile düzeltilmiş değere bölüyor).
        """
        wheel = self.wheel_distance_corrected_km
        if not wheel or wheel <= 0:
            return None
        return self.distance_km / wheel

    @property
    def label(self) -> str:
        return i18n.date_time(self.start_dt)

    def duration_text(self) -> str:
        return i18n.duration(self.duration_sec)

    # --- Ayrıştırma ----------------------------------------------------------

    @staticmethod
    def from_json(o: Mapping[str, Any], source: str = "") -> "Trip":
        records = []
        for r in o.get("records") or []:
            if isinstance(r, Mapping):
                rec = PerfRecord.from_json(r)
                if rec.kind:
                    records.append(rec)
        return Trip(
            start_epoch=int(o.get("startEpoch", 0) or 0),
            end_epoch=int(o.get("endEpoch", 0) or 0),
            duration_sec=int(o.get("durationSec", 0) or 0),
            distance_km=_req_float(o, "distanceKm"),
            energy_kwh=_opt_float(o, "energyKwh"),
            regen_kwh=_opt_float(o, "regenKwh"),
            soc_start=_opt_float(o, "socStart"),
            soc_end=_opt_float(o, "socEnd"),
            range_start=_opt_float(o, "rangeStart"),
            range_end=_opt_float(o, "rangeEnd"),
            avg_speed_kmh=_opt_float(o, "avgSpeedKmh"),
            max_speed_kmh=_opt_float(o, "maxSpeedKmh"),
            temp_start=_opt_float(o, "tempStart"),
            temp_avg=_opt_float(o, "tempAvg"),
            alt_gain_m=_req_float(o, "altGainM"),
            alt_loss_m=_req_float(o, "altLossM"),
            potential_kwh=_opt_float(o, "potentialKwh"),
            consumption_kwh100=_opt_float(o, "consumptionKwh100"),
            range_bias_factor=_opt_float(o, "rangeBiasFactor"),
            wheel_distance_km=_opt_float(o, "wheelDistanceKm"),
            records=tuple(records),
            # Eski kayıtta alan yoksa 1 varsay; kaydı asla atma.
            schema_version=int(o.get("schemaVersion", 1) or 1),
            source=source,
        )

    def field_count(self) -> int:
        """Dolu alan sayısı — aynı yolculuğun iki kopyası arasında seçim yapar."""
        optional = (
            self.energy_kwh, self.regen_kwh, self.soc_start, self.soc_end,
            self.range_start, self.range_end, self.avg_speed_kmh,
            self.max_speed_kmh, self.temp_start, self.temp_avg,
            self.potential_kwh, self.consumption_kwh100,
            self.range_bias_factor, self.wheel_distance_km,
        )
        return sum(1 for v in optional if v is not None) + len(self.records)

