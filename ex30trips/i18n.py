"""Arayüz dili: Türkçe ve İngilizce.

Araç uygulamasındaki `values/` + `values-tr/` düzeninin karşılığı: metinler koda
gömülü değil, `lang/tr.py` ve `lang/en.py` tablolarında. Kod yalnızca anahtar
kullanıyor; iki tablonun anahtar kümeleri ve yer tutucuları testle eşit
tutuluyor (I18nTests), eksik çeviri çalışma anında değil testte yakalanıyor.

Sayı, tarih ve süre biçimi de dile bağlı — Türkçede ondalık virgül ve "km/s"
(saat), İngilizcede ondalık nokta ve "km/h". Biçimleyiciler bu yüzden burada;
başka modül `strftime` ya da `f"{x:.1f}"` ile kullanıcıya metin üretmemeli.

Dil süreç genelinde tek bir değer: pencere tek, iki dil aynı anda görünmüyor.
Değişince pencere kendini yeniden kuruyor (`app.TripViewer.set_language`).
Okuma arka thread'lerden de yapılabiliyor (Drive hataları orada metne
dönüşüyor); yazma yalnızca ana thread'de.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .lang import en, tr

#: Kod → kendi dilindeki adı. Menüde bu adlar görünüyor: İngilizce arayüzde
#: takılan biri "Türkçe"yi, Türkçede takılan "English"i tanır.
LANGUAGES: dict[str, str] = {"tr": "Türkçe", "en": "English"}

#: Referans dil: başka dilde eksik anahtar buradan doldurulur.
DEFAULT = "tr"

_TABLES: dict[str, dict[str, str]] = {"tr": tr.STRINGS, "en": en.STRINGS}

_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

#: `{n|trip|trips}` — tekil/çoğul seçimi. Ad, format parametrelerinden biri.
PLURAL = re.compile(r"\{(\w+)\|([^|{}]*)\|([^|{}]*)\}")

_current = DEFAULT


def language() -> str:
    return _current


def set_language(code: str) -> None:
    global _current
    if code not in LANGUAGES:
        raise ValueError(f"unknown language: {code!r}")
    _current = code


def has(key: str) -> bool:
    """Anahtar tanımlı mı — veriden türeyen anahtarlar için (perf.<tür>)."""
    return key in _TABLES[DEFAULT]


def t(key: str, **params: Any) -> str:
    """Anahtarın geçerli dildeki metni.

    Eksik anahtar önce Türkçeden, o da yoksa anahtarın kendisiyle dolar —
    arayüz asla boş etiket göstermez, eksik olan da gözle fark edilir.
    """
    template = _TABLES[_current].get(key)
    if template is None:
        template = _TABLES[DEFAULT].get(key, key)
    if "|" in template:
        template = PLURAL.sub(
            lambda m: m.group(2) if params.get(m.group(1)) == 1 else m.group(3),
            template,
        )
    return template.format(**params) if params else template


# --- Sayı ----------------------------------------------------------------------


def num(value: float | None, decimals: int = 1, dash: str = "—") -> str:
    """Sayı: Türkçede 1.234,5 · İngilizcede 1,234.5. Değer yoksa tire."""
    if value is None:
        return dash
    text = f"{value:,.{decimals}f}"
    if _current == "tr":
        # Nokta ile virgülün yer değiştirmesi: araya geçici bir karakter koyuyoruz.
        return text.replace(",", " ").replace(".", ",").replace(" ", ".")
    return text


def pct(value: float | None, decimals: int = 0) -> str:
    """Yüzde: Türkçede işaret önde (%33), İngilizcede arkada (33%)."""
    if value is None:
        return "—"
    number = num(value, decimals)
    return f"%{number}" if _current == "tr" else f"{number}%"


# --- Tarih ve süre -------------------------------------------------------------
# Ay adlarını strftime'a bırakmıyoruz: %b işletim sisteminin yerel ayarına göre
# değişiyor, Türkçe Windows'ta İngilizce arayüz "Eyl" yazardı.


def date(dt: datetime) -> str:
    if _current == "tr":
        return dt.strftime("%d.%m.%Y")
    return f"{dt.day} {_MONTHS_EN[dt.month - 1]} {dt.year}"


def date_time(dt: datetime) -> str:
    return f"{date(dt)} {clock(dt)}"


def clock(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def axis_label(dt: datetime, kind: str) -> str:
    """Grafik ekseni etiketi. `kind`: time | day | daytime | month."""
    if kind == "time":
        return clock(dt)
    if _current == "tr":
        return dt.strftime({"day": "%d.%m", "daytime": "%d.%m %H:%M", "month": "%m.%y"}[kind])
    month = _MONTHS_EN[dt.month - 1]
    if kind == "day":
        return f"{dt.day} {month}"
    if kind == "daytime":
        return f"{dt.day} {month} {clock(dt)}"
    return f"{month} {dt:%y}"


def duration(total_sec: int, seconds: bool = True) -> str:
    """Süre. `seconds=False` ise saniye düşer (özet kartındaki toplam süre)."""
    total = max(0, int(total_sec))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return t("duration.hm", h=h, m=m)
    if seconds:
        return t("duration.ms", m=m, s=s)
    return t("duration.m", m=m)


# --- CSV -----------------------------------------------------------------------
# Excel ayracı ve ondalığı sistem yerel ayarından okuyor: Türkçe Excel ';' ve
# virgül bekliyor, İngilizce Excel ',' ve nokta. Dosyayı arayüz diline göre
# yazmak, çift tıklandığında sütunların doğru ayrılmasını sağlıyor.


def csv_delimiter() -> str:
    return ";" if _current == "tr" else ","


def csv_number(value: float | None, decimals: int) -> str:
    if value is None:
        return ""
    text = f"{value:.{decimals}f}"
    return text.replace(".", ",") if _current == "tr" else text


def csv_datetime(dt: datetime) -> str:
    # İngilizcede ISO: Excel her yerel ayarda tarih olarak tanıyor, ay/gün
    # sırası (ABD mi Birleşik Krallık mı) sorunu da çıkmıyor.
    return dt.strftime("%d.%m.%Y %H:%M:%S" if _current == "tr" else "%Y-%m-%d %H:%M:%S")


# --- Başlangıç dili ------------------------------------------------------------


def system_default() -> str:
    """Windows arayüz dili Türkçeyse `tr`, değilse `en`.

    Kullanıcı hiç seçim yapmamışsa geçerli. Bölge biçimi değil ARAYÜZ dili
    soruluyor: Türkiye'de yaşayıp İngilizce Windows kullanan biri İngilizce
    bekler.
    """
    try:
        import ctypes

        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()  # type: ignore[attr-defined]
        return "tr" if (langid & 0x3FF) == 0x1F else "en"  # 0x1F = LANG_TURKISH
    except (AttributeError, OSError):
        import locale

        name = (locale.getlocale()[0] or "").lower()
        return "tr" if name.startswith(("tr", "turkish")) else "en"


def resolve(cli: str | None = None, saved: str | None = None) -> str:
    """Açılış dili. Öncelik: komut satırı > kayıtlı seçim > işletim sistemi."""
    for candidate in (cli, saved):
        if candidate in LANGUAGES:
            return candidate  # type: ignore[return-value]
    return system_default()
