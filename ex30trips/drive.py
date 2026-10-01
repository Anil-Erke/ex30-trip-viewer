"""Yolculuk kayıtlarını Google Drive'dan indirme (protokol 3).

Araçtaki **EX30 Telemetry** her yolculuğu bitince sürücünün araçta bağladığı
Google hesabının **kendi Drive'ına** yazıyor: özet (`trip-<e>.json`) ve GPS izi
(`trip-<e>.csv.gz`) ayrı dosya, yalnızca oluşturulur, asla değişmez. Bu modül
okuma tarafı: Drive REST v3'ten listeyi alıp yeni özetleri yerel bir önbelleğe
yazıyor; geri kalan her şey (ayrıştırma, birleştirme) değişmeden `loader`
üzerinden yürüyor.

Protokolün tek kaynağı EX30 Telemetry deposundaki `drive-sync/PROTOKOL.md`
(sürüm 3). Buradaki her kural oradaki bir maddenin karşılığı; değişecekse önce
orası değişir (araç, telefon ve bu uygulama birlikte etkileniyor).

Arada sunucu yok. Kimlik doğrulama `auth` modülünde; buraya yalnızca "bana bir
access token ver / yenile / unut" diyen bir nesne geliyor (`TokenSource`).
Bu uygulama Drive'a **hiç yazmıyor** — izni olsa da (§4.6). Tek yazar araç.

Ağ çağrıları pencereyi kilitlemesin diye bu modüldeki hiçbir şey Tkinter
bilmiyor; çağıran taraf arka thread'de çalıştırıp sonucu kendi marshal ediyor.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Protocol

from . import i18n

#: Bağlantı ve okuma için üst sınır. Saatlik bir iz ~70 KB, ama araç hattı
#: yavaş olabiliyor; kısa zaman aşımı yarım inen dosya üretir (MD5 yakalar ama
#: boşa tekrar ettirir).
TIMEOUT_S = 60

#: Aynı anda indirilen özet sayısı. İstek başına gecikme ~100-300 ms; ilk
#: eşitlemede 300 özeti sırayla indirmek bir dakikayı bulurdu. Drive'ın
#: kullanıcı başına kotası (saniyede onlarca istek) buna rahat yetiyor.
CONCURRENCY = 4

#: Yıl/ay klasörü yolculuk başlangıcına göre, İstanbul saatinde (§2). Türkiye
#: 2016'dan beri yaz saati uygulamıyor, sabit UTC+3. `zoneinfo` kullanılmıyor:
#: Windows'ta saat dilimi veritabanı yok, `tzdata` paketi gerekirdi.
ISTANBUL = timezone(timedelta(hours=3))

#: `trip-<startEpoch>.json` | `trip-<startEpoch>.csv.gz` — `ex30id` değeri.
TRIP_RE = re.compile(r"^trip-(\d{13})\.(json|csv\.gz)$")

FILES_URL = "https://www.googleapis.com/drive/v3/files"

#: İstenen alanlar (§4.1). `appProperties` eşleşmenin kendisi: dosya taşınsa ya
#: da adı değişse de `ex30id` aynı kalıyor.
LIST_FIELDS = "nextPageToken,files(id,name,createdTime,size,md5Checksum,appProperties)"

#: Yolculuk dosyalarının sorgusu. Klasörler ve kökteki günlükler (`kayit`)
#: bilerek dışarıda.
TRIP_QUERY = "appProperties has { key='ex30' and value='trip' } and trashed=false"

#: İmleç bir sonraki istekte bu kadar geri çekiliyor (§4.2): Drive listesi yeni
#: oluşturulan dosyayı kısa bir gecikmeyle gösterebiliyor; tam imleçten sormak
#: o dosyayı bir daha hiç göstermeyebilirdi. Örtüşme `ex30id` ile tekleniyor.
CURSOR_OVERLAP = timedelta(minutes=5)

#: İmleçsiz tam listenin en seyrek aralığı (§4.7). Drive'da sürüm 2'deki
#: `toplam` yok; imlecin gerisinde kalan bir dosyayı (saat kayması, gecikmeli
#: dizinleme) yakalamanın yolu arada bir her şeyi listelemek. Yalnızca
#: metadata: 1000 dosya başına tek istek.
FULL_SCAN_EVERY = timedelta(days=1)

#: 429 / hız sınırı / 5xx'te bekleme süreleri (saniye); tükenince hata.
BACKOFF_S = (1.0, 2.0, 4.0)

#: Hız sınırını bildiren 403 nedenleri (§4.8). 403'ün geri kalanı izin sorunu.
RATE_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})


class DriveError(Exception):
    """İndirme başarısız. Mesaj kullanıcıya olduğu gibi gösteriliyor.

    Sebep dil anahtarıyla taşınıyor, `str()` anında geçerli dile çevriliyor —
    hata arka thread'de doğup ekrana başka bir dil açıkken basılabiliyor.
    """

    #: Kullanıcı yeniden giriş yapmadan düzelmez (token öldü, izin yok).
    relogin = False

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params

    def __str__(self) -> str:
        return i18n.t(self.key, **self.params)


class AuthError(DriveError):
    """Google hesabıyla ilgili, ancak yeniden girişle çözülen hata."""

    relogin = True


# --- Yerel yollar ----------------------------------------------------------------


def config_dir() -> Path:
    """Ayarların ve indirilen dosyaların yeri.

    `%LOCALAPPDATA%` kullanılıyor çünkü tek dosya kipinde exe kendini her
    açılışta geçici bir klasöre açıyor (`sys._MEIPASS`) ve oraya yazılan hiçbir
    şey kalıcı olmuyor — ayarlar exe'nin yanında tutulamaz.
    """
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home()
    return root / "EX30TripViewer"


def accounts_dir() -> Path:
    return config_dir() / "hesaplar"


def _folder_name(email: str) -> str:
    """E-postadan klasör adı. Gmail adresinde Windows'un yasak karakterleri
    zaten olamıyor; yine de başka bir alan adından gelecek adres klasör
    yolunu kaçırmasın."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", email.strip().lower())
    return name.strip(" .") or "_"


def summary_name(epoch: int) -> str:
    return f"trip-{epoch}.json"


def track_name(epoch: int) -> str:
    return f"trip-{epoch}.csv.gz"


def _write_atomic(path: Path, data: bytes) -> None:
    """Önce geçici dosyaya, sonra yerine. Yarıda kesilen yazma (kapanan
    pencere, dolu disk) önbellekte yarım bir özet bırakırsa o dosya "inmiş"
    sayılır ve bir daha hiç indirilmezdi."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".part")
    temp.write_bytes(data)
    os.replace(temp, path)


# --- Zaman -------------------------------------------------------------------------


def parse_time(value: str | None) -> datetime | None:
    """Drive'ın RFC 3339 zamanı (`2026-09-29T08:12:33.123Z`) → UTC datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_time(when: datetime) -> str:
    """UTC, milisaniyeli, `Z` ile — Drive'ın kendi yazdığı biçim. Sorguda da
    bu biçim kullanılıyor; saat dilimi eki farklı yazılırsa karşılaştırma
    yine doğru ama günlükte iki biçim görmek kafa karıştırıyor."""
    utc = when.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


# --- Drive dosyası -----------------------------------------------------------------


@dataclass(frozen=True)
class DriveFile:
    """Listedeki bir yolculuk dosyası (§2.1)."""

    id: str
    #: Tekil anahtar, ör. `trip-1790602585477.json`.
    ex30id: str
    epoch: int
    kind: str  # "ozet" | "iz"
    md5: str | None = None
    size: int | None = None
    created: str = ""

    @property
    def is_summary(self) -> bool:
        return self.kind == "ozet"

    @property
    def is_track(self) -> bool:
        return self.kind == "iz"

    def to_json(self) -> dict:
        return {"id": self.id, "md5": self.md5, "boyut": self.size, "olusturuldu": self.created}

    @classmethod
    def track_from_json(cls, epoch: int, data: object) -> "DriveFile | None":
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            return None
        size = data.get("boyut")
        md5 = data.get("md5")
        return cls(
            id=data["id"],
            ex30id=track_name(epoch),
            epoch=epoch,
            kind="iz",
            md5=md5 if isinstance(md5, str) else None,
            size=size if isinstance(size, int) else None,
            created=str(data.get("olusturuldu") or ""),
        )


def _file_from(row: object) -> DriveFile | None:
    """`files.list` satırı → DriveFile. Tanınmayan satır None.

    Tek bir bozuk satır bütün listeyi düşürmüyor: ileride Drive'a başka tür
    dosya girebilir, kullanıcı elle bir şey ekleyebilir.
    """
    if not isinstance(row, dict) or not isinstance(row.get("id"), str):
        return None
    props = row.get("appProperties")
    if not isinstance(props, dict) or props.get("ex30") != "trip":
        return None
    ex30id = props.get("ex30id")
    match = TRIP_RE.match(ex30id) if isinstance(ex30id, str) else None
    kind = props.get("tur")
    if not match or kind not in ("ozet", "iz"):
        return None
    # Tür adla tutmalı; tutmuyorsa satır bozuk (özet diye bir gzip indirirdik).
    if (kind == "ozet") != (match.group(2) == "json"):
        return None
    epoch = int(match.group(1))
    # `epoch` özelliği adla çelişiyorsa hangisine güveneceğimizi bilemeyiz.
    declared = props.get("epoch")
    if declared is not None and str(declared) != str(epoch):
        return None
    size = row.get("size")
    try:
        size = int(size) if size is not None else None
    except (TypeError, ValueError):
        size = None
    md5 = row.get("md5Checksum")
    return DriveFile(
        id=row["id"],
        ex30id=ex30id,
        epoch=epoch,
        kind=kind,
        md5=md5 if isinstance(md5, str) else None,
        size=size,
        created=str(row.get("createdTime") or ""),
    )


def parse_files(raw: bytes) -> tuple[list[DriveFile], str | None]:
    """Bir `files.list` sayfası → (dosyalar, `nextPageToken`)."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DriveError("drive.err.bad_shape") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("files", []), list):
        raise DriveError("drive.err.bad_shape")
    files = [f for f in map(_file_from, payload.get("files", [])) if f is not None]
    token = payload.get("nextPageToken")
    return files, token if isinstance(token, str) and token else None


def trips_query(since: datetime | None) -> str:
    """Yolculuk listesinin `q`'su; `since` None ise imleçsiz tam liste."""
    if since is None:
        return TRIP_QUERY
    return f"{TRIP_QUERY} and createdTime > '{format_time(since)}'"


def check_md5(record: DriveFile, blob: bytes) -> None:
    """Bütünlük ölçütü (§4.8): yarım inen ya da yolda bozulan dosyayı
    sessizce kabul etmek, eksik veriyi "inmiş" saymak demek. Drive MD5
    vermediyse (olmaması gerekir) boyutla yetiniyoruz."""
    if record.md5:
        got = hashlib.md5(blob).hexdigest()
        if got.lower() != record.md5.lower():
            raise DriveError("drive.err.md5", name=record.ex30id, expected=record.md5[:8], got=got[:8])
    elif record.size is not None and record.size != len(blob):
        raise DriveError("drive.err.size", name=record.ex30id, expected=record.size, got=len(blob))


# --- Ağ ------------------------------------------------------------------------------

#: (yöntem, adres, başlıklar, gövde) → (HTTP kodu, gövde). Testte sahtesi.
Transport = Callable[[str, str, dict[str, str], "bytes | None"], tuple[int, bytes]]


def http_request(method: str, url: str, headers: dict[str, str], body: bytes | None = None) -> tuple[int, bytes]:
    """Tek HTTP isteği. HTTP hata kodları istisna değil, dönüş değeri: Drive
    gerçek kodlar döndürüyor ve karar onlara göre veriliyor (§4.8). Yalnızca
    bağlantı kurulamaması `DriveError`."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read()
        finally:
            e.close()
    except urllib.error.URLError as e:
        raise DriveError("drive.err.connect", reason=e.reason) from e
    except OSError as e:
        raise DriveError("drive.err.connect", reason=e) from e


def _error_info(raw: bytes) -> tuple[str, str]:
    """Drive hata gövdesinden (neden, ileti). Gövde JSON değilse boş."""
    try:
        error = json.loads(raw.decode("utf-8")).get("error")
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return "", ""
    if not isinstance(error, dict):
        return "", ""
    reasons = [e.get("reason") for e in error.get("errors") or [] if isinstance(e, dict)]
    reason = next((r for r in reasons if isinstance(r, str)), "")
    message = error.get("message")
    return reason, message if isinstance(message, str) else ""


class TokenSource(Protocol):
    """Drive'a giden isteğin kimliği. Gerçeği `auth.Session`."""

    def access_token(self) -> str: ...

    def refresh(self, stale: str) -> None:
        """`stale` reddedildi; yenisini al. Başka bir thread zaten yenilediyse
        bir şey yapmaz — dört paralel indirme aynı anda 401 alabiliyor."""

    def forget(self) -> None:
        """Saklanan token'ı sil: yeniden giriş gerekiyor."""


class Api(Protocol):
    """Drive'a giden okuma istekleri. Gerçeği `HttpApi`."""

    def list_trips(self, since: datetime | None) -> list[DriveFile]: ...

    def find(self, ex30id: str) -> DriveFile | None: ...

    def download(self, record: DriveFile) -> bytes: ...


class HttpApi:
    """Drive REST v3 — yalnızca okuma."""

    def __init__(
        self,
        tokens: TokenSource,
        transport: Transport = http_request,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.tokens = tokens
        self.transport = transport
        self.sleep = sleep

    def _get(self, url: str, name: str = "") -> bytes:
        """GET + hata politikası (§4.8).

        401 → token'ı yenile, BİR KEZ tekrar dene; yenisi de reddedilirse
        erişim geri alınmış demektir. 403 izin → yeniden giriş. 429 / hız
        sınırı / 5xx → geri çekil.
        """
        refreshed = False
        attempt = 0
        while True:
            token = self.tokens.access_token()
            status, body = self.transport(
                "GET", url, {"Authorization": f"Bearer {token}", "User-Agent": "EX30TripViewer"}, None
            )
            if status == 200:
                return body
            reason, message = _error_info(body)
            if status == 401:
                if not refreshed:
                    self.tokens.refresh(token)
                    refreshed = True
                    continue
                self.tokens.forget()
                raise AuthError("auth.err.expired")
            if status == 403 and reason not in RATE_REASONS:
                # En olası sebep: onay ekranında Drive kutusu boş bırakıldı ya
                # da izin sonradan geri alındı. Token'ı tutmak bir şey
                # kazandırmıyor; her çağrı yine 403 döner.
                self.tokens.forget()
                raise AuthError("drive.err.no_permission")
            if status == 429 or status == 403 or status >= 500:
                if attempt < len(BACKOFF_S):
                    self.sleep(BACKOFF_S[attempt])
                    attempt += 1
                    continue
                if status >= 500:
                    raise DriveError("drive.err.http", code=status, message=message or "—")
                raise DriveError("drive.err.rate_limit")
            if status == 404:
                raise DriveError("drive.err.not_found", name=name or "?")
            raise DriveError("drive.err.http", code=status, message=message or "—")

    def _list(self, query: str) -> list[DriveFile]:
        """Sorgunun bütün sayfaları. Tek sayfa bile inmezse hepsi gider:
        yarım listeyle imleci ilerletmek sayfaların arasında kalanı kaçırırdı."""
        found: list[DriveFile] = []
        page: str | None = None
        while True:
            params = {
                "q": query,
                "fields": LIST_FIELDS,
                "orderBy": "createdTime",
                "pageSize": "1000",
                "spaces": "drive",
            }
            if page:
                params["pageToken"] = page
            files, page = parse_files(self._get(f"{FILES_URL}?{urllib.parse.urlencode(params)}"))
            found.extend(files)
            if not page:
                return found

    def list_trips(self, since: datetime | None) -> list[DriveFile]:
        return self._list(trips_query(since))

    def find(self, ex30id: str) -> DriveFile | None:
        """Tek dosyayı `ex30id` ile arar — hiç eşitlenmemiş hesapta izi
        indirebilmek için (liste yoksa dosyanın kimliği de bilinmiyor)."""
        if not TRIP_RE.match(ex30id):
            return None
        query = f"{TRIP_QUERY} and appProperties has {{ key='ex30id' and value='{ex30id}' }}"
        for record in self._list(query):
            if record.ex30id == ex30id:
                return record
        return None

    def download(self, record: DriveFile) -> bytes:
        """Dosyanın ham baytı (§4.8): özet düz JSON, iz gzip. Zarf yok."""
        blob = self._get(f"{FILES_URL}/{urllib.parse.quote(record.id)}?alt=media", record.ex30id)
        check_md5(record, blob)
        return blob


# --- Hesap önbelleği -----------------------------------------------------------------


@dataclass
class SyncState:
    #: Görülen en büyük `createdTime`, Drive'ın yazdığı gibi; hiç yoksa None.
    cursor: str | None = None
    #: Son başarılı imleçsiz tam listenin zamanı (UTC, RFC 3339).
    last_full: str | None = None
    #: Drive'da izi olduğu bilinen yolculuklar (inmiş olsun olmasın). İzin
    #: dosya kimliği yalnızca listeden öğreniliyor; "iz yok"u da ağa çıkmadan
    #: söylemeye yarıyor.
    tracks: dict[int, DriveFile] = field(default_factory=dict)

    @property
    def listed(self) -> bool:
        """En az bir liste başarıyla işlendi mi."""
        return self.cursor is not None or self.last_full is not None


class AccountCache:
    """Bir Google hesabının yerel kopyası:
    `%LOCALAPPDATA%\\EX30TripViewer\\hesaplar\\<e-posta>\\`.

    Hesap başına ayrı: aynı bilgisayarda iki kişi kendi hesabıyla girebilir,
    birinin yolculukları ötekinin listesine karışmaz. Çıkış bu klasörü siliyor.
    """

    def __init__(self, email: str) -> None:
        self.email = email
        self.root = accounts_dir() / _folder_name(email)

    @property
    def trips_dir(self) -> Path:
        """Drive'daki `yolculuklar/` ile aynı yıl/ay düzeni. Drive kaynağı bu
        klasörün tamamı; düzen aynı tutuluyor ki biri Drive'daki klasörü elle
        indirip "Klasör ekle" ile açtığında da aynı şeyi görsün."""
        return self.root / "yolculuklar"

    @property
    def state_path(self) -> Path:
        return self.root / "esitleme.json"

    def month_dir(self, epoch: int) -> Path:
        when = datetime.fromtimestamp(epoch / 1000.0, ISTANBUL)
        return self.trips_dir / f"{when:%Y}" / f"{when:%m}"

    def summary_path(self, epoch: int) -> Path:
        return self.month_dir(epoch) / summary_name(epoch)

    def track_path(self, epoch: int) -> Path:
        return self.month_dir(epoch) / track_name(epoch)

    def known_summaries(self) -> set[int]:
        """Önbellekteki özetlerin `startEpoch`'ları. Dosyalar değişmediği için
        diskte olan, inmiş demek — ayrıca bir liste tutmuyoruz."""
        if not self.trips_dir.is_dir():
            return set()
        found: set[int] = set()
        for path in self.trips_dir.rglob("trip-*.json"):
            match = TRIP_RE.match(path.name)
            if match and match.group(2) == "json":
                found.add(int(match.group(1)))
        return found

    def load_state(self) -> SyncState:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return SyncState()
        if not isinstance(data, dict):
            return SyncState()
        tracks: dict[int, DriveFile] = {}
        raw_tracks = data.get("izler")
        if isinstance(raw_tracks, dict):
            for key, value in raw_tracks.items():
                if isinstance(key, str) and key.isdigit():
                    record = DriveFile.track_from_json(int(key), value)
                    if record is not None:
                        tracks[record.epoch] = record
        cursor = data.get("imlec")
        last_full = data.get("sonTamTarama")
        return SyncState(
            cursor=cursor if isinstance(cursor, str) and parse_time(cursor) else None,
            last_full=last_full if isinstance(last_full, str) and parse_time(last_full) else None,
            tracks=tracks,
        )

    def save_state(self, state: SyncState) -> None:
        payload = {
            "imlec": state.cursor,
            "sonTamTarama": state.last_full,
            "izler": {str(e): r.to_json() for e, r in sorted(state.tracks.items())},
        }
        _write_atomic(self.state_path, json.dumps(payload, indent=1).encode("utf-8"))

    def clear(self) -> None:
        """Hesabın bütün yerel kopyası: özetler, izler, imleç."""
        shutil.rmtree(self.root, ignore_errors=True)


# --- Sürüm 2'den geçiş (§4.1) --------------------------------------------------------

#: Sürüm 2'nin `config_dir()` altında bıraktıkları: adres + okuma anahtarı,
#: imleç, özet/iz önbelleği, `trips.json` kopyası. Hepsi Apps Script
#: dünyasına ait; sürüm 3 istemcisi o dosyaları göremiyor bile (`drive.file`).
LEGACY_ENTRIES = ("drive.json", "esitleme.json", "yolculuklar", "indirilen")


def migrate_v2() -> bool:
    """Sürüm 2 ayarını ve önbelleğini siler. @return bir şey silindiyse True.

    İçlerinde sürüm 3'te yeniden inmeyecek bir şey yok: araç sürüm 2 dosyası
    hiç üretmedi, `trips.json` kopyası da araçtaki yolculuklardan ibaret ve
    araç hesap bağlanınca hepsini Drive'a gönderiyor. "Bir kez" ayrıca
    kaydedilmiyor: silinen şey bir daha yok, sonraki açılışta iş kalmıyor.
    `settings.json` (dil) ve `hesaplar/` dokunulmuyor.
    """
    root = config_dir()
    removed = False
    for name in LEGACY_ENTRIES:
        path = root / name
        try:
            if path.is_dir():
                shutil.rmtree(path)
                removed = True
            elif path.exists():
                path.unlink()
                removed = True
        except OSError:
            # Açık bir dosya silmeyi engelleyebilir; bir sonraki açılışta
            # yeniden denenir. Açılış bunun yüzünden düşmesin.
            pass
    return removed


# --- Artımlı eşitleme (§4) -----------------------------------------------------------


@dataclass(frozen=True)
class SyncResult:
    #: Yüklenecek kaynak: hesabın önbellek klasörü.
    path: Path
    new_trips: int = 0
    #: Listede gelen (teklenmiş) kayıt sayısı.
    listed: int = 0
    #: Eşitlemeden sonra önbellekteki özet sayısı.
    local: int = 0
    #: Bu eşitleme imleçsiz tam liste aldı.
    full_scan: bool = False
    #: Son başarılı tam listenin zamanı (UTC); hiç yoksa None.
    last_full: datetime | None = None
    cursor_advanced: bool = False
    #: Hata metinleri (ilk birkaç yeter); `failed` inemeyen özet sayısı.
    errors: tuple[str, ...] = ()
    failed: int = 0


def needs_full_scan(state: SyncState, now: datetime) -> bool:
    """İmleçsiz tam liste gerekiyor mu (§4.7): ilk eşitleme ya da son tam
    listeden bu yana bir gün geçti. Saat geri alınmışsa (son tarama
    "gelecekte") da tam liste — imlecin anlamı kalmamış olabilir."""
    if state.cursor is None:
        return True
    last = parse_time(state.last_full)
    if last is None:
        return True
    return now - last >= FULL_SCAN_EVERY or now < last


def _check_summary(record: DriveFile, blob: bytes) -> None:
    """Özet tek bir JSON nesnesi olmalı ve `startEpoch`'u adıyla tutmalı.

    Araç bunu yazarken doğruluyor; yine de tutmuyorsa yanlış yolculuğun izi
    yanlış özetle eşleşirdi.
    """
    try:
        data = json.loads(blob.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DriveError("drive.err.bad_summary", name=record.ex30id) from None
    if not isinstance(data, dict) or data.get("startEpoch") != record.epoch:
        raise DriveError("drive.err.bad_summary", name=record.ex30id)


def sync(
    api: Api,
    cache: AccountCache,
    *,
    full: bool = False,
    progress: Callable[[int, int], None] | None = None,
    now: datetime | None = None,
) -> SyncResult:
    """"Drive'dan al"ın bütün işi. ARKA THREAD'de çağrılır.

    1. İmleç − 5 dk'dan sonra oluşturulanların listesi; ilk seferde, günde
       bir kez ve `full` ile (kullanıcı "baştan tara" dedi) imleçsiz.
    2. Kayıtlar `ex30id` ile teklenir: örtüşme penceresindeki dosya iki
       listede birden gelir.
    3. Yerelde olmayan her özet indirilir, MD5'i denetlenir ve HEMEN diske
       yazılır — yarıda kesilen ilk eşitleme bir sonrakinde baştan başlamasın.
    4. İzler burada İNDİRİLMİYOR, yalnızca kimlikleri kaydediliyor; yolculuk
       açılınca iniyor.
    5. **İmleç ancak listedeki her şey başarıyla indiyse ilerler** (§4.5).
       Bir özet inmezse imleç yerinde kalır; sonraki eşitleme aynı listeyi
       yeniden alır, inenleri atlar, kalanı dener.

    Liste alınamazsa `DriveError` fırlatır; tek tek özet hataları sonuçta
    toplanır (biri inmedi diye inenler atılmaz).
    """
    now = now or datetime.now(timezone.utc)
    report = progress or (lambda _done, _total: None)

    state = cache.load_state()
    full_scan = full or needs_full_scan(state, now)
    cursor = parse_time(state.cursor)
    since = None if full_scan or cursor is None else cursor - CURSOR_OVERLAP

    by_id: dict[str, DriveFile] = {}
    for record in api.list_trips(since):
        by_id.setdefault(record.ex30id, record)
    unique = list(by_id.values())

    summaries = cache.known_summaries()
    wanted: dict[int, DriveFile] = {}
    for record in unique:
        if record.is_summary and record.epoch not in summaries:
            wanted.setdefault(record.epoch, record)
    listed_tracks = {r.epoch: r for r in unique if r.is_track}
    if full_scan:
        # Tam liste Drive'daki durumun kendisi: çöpe atılmış izler de düşsün.
        state.tracks = listed_tracks
    else:
        state.tracks.update(listed_tracks)

    todo = list(wanted.values())
    done = saved = 0
    errors: list[str] = []
    report(0, len(todo))

    def fetch_one(record: DriveFile) -> None:
        blob = api.download(record)
        _check_summary(record, blob)
        try:
            _write_atomic(cache.summary_path(record.epoch), blob)
        except OSError as e:
            raise DriveError("drive.err.save", error=e) from e

    with ThreadPoolExecutor(max_workers=CONCURRENCY, thread_name_prefix="DriveSync") as pool:
        futures = [pool.submit(fetch_one, record) for record in todo]
        for future in futures:
            try:
                future.result()
                saved += 1
            except DriveError as e:
                errors.append(str(e))
            except Exception as e:  # tek bir özet bütün eşitlemeyi düşürmesin
                errors.append(i18n.t("drive.err.unexpected", error=e))
            done += 1
            report(done, len(todo))

    failed = len(errors)
    advanced = not errors
    if advanced:
        # Karşılaştırma zamanla, metinle değil: Drive'ın biçimi hep aynı
        # görünse de sözlük sırası buna yaslanmasın.
        seen = [(when, r.created) for r in unique if (when := parse_time(r.created)) is not None]
        if seen:
            newest_time, newest_text = max(seen)
            if cursor is None or newest_time > cursor:
                state.cursor = newest_text
        if full_scan:
            state.last_full = format_time(now)
    try:
        cache.save_state(state)
    except OSError as e:
        # İmleç kaydedilemedi: inen özetler diskte, bir sonraki eşitleme
        # onları atlayıp listeyi yeniden alır — veri kaybı yok.
        errors.append(i18n.t("drive.err.save", error=e))
        advanced = False

    return SyncResult(
        path=cache.trips_dir,
        new_trips=saved,
        listed=len(unique),
        local=len(cache.known_summaries()),
        full_scan=full_scan,
        last_full=parse_time(state.last_full),
        cursor_advanced=advanced,
        errors=tuple(errors[:5]),
        failed=failed,
    )


# --- GPS izi ----------------------------------------------------------------------


def track_known_missing(cache: AccountCache, epoch: int) -> bool:
    """İzin Drive'da OLMADIĞI ağa çıkmadan biliniyor mu: bu hesapla en az bir
    liste alındıysa izi olan bütün yolculuklar kayıtlı, listede `tur=iz`
    kaydı olmayan yolculuğun izi yok (0.7.2 öncesi, GPS'siz sürüş).
    Hiç eşitlenmediyse bilinmiyor — o zaman sormak gerekiyor."""
    if cache.track_path(epoch).exists():
        return False
    state = cache.load_state()
    return state.listed and epoch not in state.tracks


def download_track(api: Api, cache: AccountCache, epoch: int) -> Path | None:
    """İzi önbelleğe indirir; zaten varsa ağa çıkmaz. İz yoksa None.

    Önbellekte Drive'daki gibi gzip'li ve BAYTI BAYTINA aynı saklanıyor: MD5
    denetimi indirilen içerik üzerinde yapıldı, yeniden sıkıştırmak bir şey
    kazandırmaz. MD5 tutmazsa diske hiçbir şey yazılmıyor.
    """
    path = cache.track_path(epoch)
    if path.exists():
        return path
    state = cache.load_state()
    record = state.tracks.get(epoch)
    if record is None:
        if state.listed:
            return None
        record = api.find(track_name(epoch))
        if record is None:
            return None
    blob = api.download(record)
    try:
        _write_atomic(path, blob)
    except OSError as e:
        raise DriveError("drive.err.save", error=e) from e
    return path
