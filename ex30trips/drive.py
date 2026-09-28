"""Yolculuk kayıtlarını Google Drive'dan indirme.

Araçtaki **EX30 Telemetry**, "Drive'a aktar" düğmesine basıldığında dosyaları
kullanıcının kendi Drive klasörüne yüklüyor (`calib/DriveUploader.kt`). Bu modül
aynı ucun okuma tarafı: dosyayı indirip yerel bir önbelleğe yazıyor, geri kalan
her şey (ayrıştırma, birleştirme) değişmeden `loader` üzerinden yürüyor.

Neden Drive API değil: araçtaki uygulamanın tarayıcısı yok, bu yüzden OAuth
yerine kullanıcının kendi hesabında yayınladığı bir Apps Script web uygulaması
kullanılıyor. Aynı ucu burada da kullanmak ikinci bir kimlik doğrulama yolu
açmaktan basit. Kurulum: EX30 Telemetry deposundaki `drive-sync/README.md`.

**Okuma anahtarı yazma anahtarından ayrı.** Araçtaki anahtar APK'nın içinde
gidiyor ve geri derlenebiliyor; buradaki anahtar yalnızca bu bilgisayardaki ayar
dosyasında duruyor. İkisi aynı olursa APK'yı açan biri yolculuk geçmişini de
indirebilir hâle gelir.

Ağ çağrıları pencereyi kilitlemesin diye bu modüldeki hiçbir şey Tkinter
bilmiyor; çağıran taraf arka thread'de çalıştırıp sonucu kendi marshal ediyor.
"""

from __future__ import annotations

import base64
import gzip
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import i18n

#: Viewer'ın okuduğu tek dosya. Araçtaki DataExporter.FILES listesinin bir üyesi.
TRIPS_NAME = "trips.json"

#: Bağlantı ve okuma için üst sınır. Araç hattından yüklenen dosya büyük
#: olabiliyor; kısa bir zaman aşımı yarım inen dosya üretir.
TIMEOUT_S = 60


class DriveError(Exception):
    """İndirme başarısız. Mesaj kullanıcıya olduğu gibi gösteriliyor.

    Sebep dil anahtarıyla taşınıyor, `str()` anında geçerli dile çevriliyor.
    Sunucunun kendi hata metni (`hata` alanı) `drive.err.server` ile
    değiştirilmeden aktarılıyor — onu çevirmek bizim işimiz değil.
    """

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params

    def __str__(self) -> str:
        return i18n.t(self.key, **self.params)


def config_dir() -> Path:
    """Ayarların ve indirilen dosyanın yeri.

    `%LOCALAPPDATA%` kullanılıyor çünkü tek dosya kipinde exe kendini her
    açılışta geçici bir klasöre açıyor (`sys._MEIPASS`) ve oraya yazılan hiçbir
    şey kalıcı olmuyor — ayarlar exe'nin yanında tutulamaz.
    """
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home()
    return root / "EX30TripViewer"


def config_path() -> Path:
    return config_dir() / "drive.json"


def cache_path(name: str = TRIPS_NAME) -> Path:
    """İndirilen dosyanın yazıldığı yer.

    Dosya diske yazılıyor ki uygulama kapanıp açıldığında ya da ağ yokken
    "Yenile" (F5) aynı veriyi tekrar okuyabilsin.
    """
    return config_dir() / "indirilen" / name


@dataclass(frozen=True)
class Config:
    url: str = ""
    secret: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.url.strip()) and bool(self.secret.strip())


def load_config() -> Config:
    """Ayarları okur. Dosya yoksa ya da bozuksa boş ayar döner — çökmez."""
    path = config_path()
    if not path.exists():
        return Config()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Config()
    if not isinstance(data, dict):
        return Config()
    return Config(
        url=str(data.get("url") or "").strip(),
        secret=str(data.get("secret") or "").strip(),
    )


def save_config(config: Config) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"url": config.url, "secret": config.secret}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_url(config: Config, name: str) -> str:
    sep = "&" if "?" in config.url else "?"
    query = urllib.parse.urlencode({"k": config.secret, "file": name})
    return f"{config.url}{sep}{query}"


def parse_response(raw: str) -> bytes:
    """Sunucu yanıtını dosya içeriğine çevirir.

    **Başarı ölçütü HTTP durum kodu değil.** Apps Script web uygulaması durum
    kodu döndüremiyor; yetki hatası da, "dosya yok" da 200 ile geliyor. Tek
    geçerli ölçüt gövdedeki ``ok`` alanı.
    """
    if not raw.strip():
        raise DriveError("drive.err.empty")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # Yapılandırma yanlışsa Google'ın HTML oturum açma sayfası geliyor.
        raise DriveError("drive.err.not_json") from None

    if not isinstance(payload, dict):
        raise DriveError("drive.err.bad_shape")
    if not payload.get("ok"):
        message = payload.get("hata")
        if message:
            raise DriveError("drive.err.server", message=str(message))
        raise DriveError("drive.err.unknown_server")

    data = payload.get("data")
    if not isinstance(data, str) or not data:
        raise DriveError("drive.err.no_data")

    try:
        blob = base64.b64decode(data, validate=True)
    except (ValueError, TypeError) as e:
        raise DriveError("drive.err.base64", error=e) from e

    if payload.get("gz"):
        try:
            blob = gzip.decompress(blob)
        except (OSError, EOFError) as e:
            raise DriveError("drive.err.gzip", error=e) from e

    expected = payload.get("bytes")
    if isinstance(expected, int) and expected != len(blob):
        # Yarım inen dosyayı sessizce kabul etmek, eski veriyi bozuk veriyle
        # değiştirmek demek.
        raise DriveError("drive.err.size", expected=expected, got=len(blob))

    return blob


def fetch(config: Config, name: str = TRIPS_NAME) -> bytes:
    """Dosyayı indirir. Ağ hataları `DriveError`'a çevriliyor."""
    if not config.ready:
        raise DriveError("drive.err.not_configured")

    request = urllib.request.Request(
        build_url(config, name),
        headers={"User-Agent": "EX30TripViewer"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise DriveError("drive.err.http", code=e.code) from e
    except urllib.error.URLError as e:
        raise DriveError("drive.err.connect", reason=e.reason) from e
    except OSError as e:
        raise DriveError("drive.err.connect", reason=e) from e

    return parse_response(raw)


def download(config: Config, name: str = TRIPS_NAME) -> Path:
    """İndirip önbelleğe yazar ve dosyanın yolunu döner."""
    blob = fetch(config, name)
    path = cache_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(blob)
    except OSError as e:
        raise DriveError("drive.err.save", error=e) from e
    return path
