"""Çalıştırma: proje kökünde  py -3 -m unittest discover -s tests

Testlerin çapası gerçek veri: `ornek/trips-ornek.txt` araçtan çıkmış bir dışa
aktarım. Beklenen değerler oradaki sayılardan elle hesaplandı.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import math
import os
import re
import string
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from matplotlib.figure import Figure  # noqa: E402

from ex30trips import app as app_module  # noqa: E402
from ex30trips import auth, charts, drive, i18n, settings, stats  # noqa: E402
from ex30trips import track as gps  # noqa: E402
from ex30trips.__main__ import split_language  # noqa: E402
from ex30trips.lang import en as lang_en  # noqa: E402
from ex30trips.lang import tr as lang_tr  # noqa: E402
from ex30trips.loader import (  # noqa: E402
    LoadResult,
    Source,
    TripFileError,
    combine,
    load,
    merge,
    read_file,
)
from ex30trips.model import WHEEL_TICK_SCALE, Trip  # noqa: E402

SAMPLE = ROOT / "ornek" / "trips-ornek.txt"

# Metin denetleyen testler Türkçe yazıldı; açılış dili makineye göre
# değişebildiği için burada sabitleniyor. İngilizce I18nTests'te.
i18n.set_language("tr")


class ModelTests(unittest.TestCase):
    def test_reads_sample(self) -> None:
        trips = read_file(SAMPLE)
        self.assertEqual(len(trips), 5)
        # En uzun yolculuk: 46,76 km, 6,555 kWh net.
        longest = max(trips, key=lambda t: t.distance_km)
        self.assertAlmostEqual(longest.distance_km, 46.7641795, places=5)
        self.assertAlmostEqual(longest.consumption, 14.0170593, places=5)
        self.assertEqual(longest.schema_version, 3)
        self.assertEqual(len(longest.records), 1)
        self.assertEqual(longest.records[0].label, "0–60 km/s")

    def test_missing_fields_stay_none(self) -> None:
        """Enerji ölçülemeyen kısa yolculukta alanlar None kalmalı, 0 değil."""
        trips = read_file(SAMPLE)
        short = min(trips, key=lambda t: t.distance_km)
        self.assertIsNone(short.energy_kwh)
        self.assertIsNone(short.consumption)
        self.assertIsNone(short.soc_drop)
        self.assertIsNone(short.range_bias_factor)

    def test_derived_values(self) -> None:
        trip = Trip.from_json(
            {
                "startEpoch": 1_700_000_000_000,
                "endEpoch": 1_700_000_360_000,
                "durationSec": 360,
                "distanceKm": 10.0,
                "energyKwh": 1.5,
                "regenKwh": 0.5,
                "socStart": 80.0,
                "socEnd": 76.0,
                "wheelDistanceKm": 10.2,
            }
        )
        self.assertAlmostEqual(trip.gross_kwh, 2.0)
        self.assertAlmostEqual(trip.regen_share, 25.0)
        self.assertAlmostEqual(trip.consumption, 15.0)  # kayıtta yok, türetildi
        self.assertAlmostEqual(trip.soc_drop, 4.0)
        # Bölen DÜZELTİLMİŞ tekerlek mesafesi (araç ve Mobile ile aynı kural).
        self.assertAlmostEqual(trip.wheel_distance_corrected_km, 10.2 * WHEEL_TICK_SCALE)
        self.assertAlmostEqual(trip.gps_wheel_ratio, 10.0 / (10.2 * WHEEL_TICK_SCALE))
        self.assertEqual(trip.duration_text(), "6 dk 00 sn")

    def test_wheel_distance_scale(self) -> None:
        # Kayıttaki değer HAM kalır; düzeltme yalnızca türetilen değerlerde.
        self.assertAlmostEqual(WHEEL_TICK_SCALE, 1.02536)
        trip = Trip.from_json(
            {"startEpoch": 1, "endEpoch": 2, "durationSec": 1, "distanceKm": 10.2536, "wheelDistanceKm": 10.0}
        )
        self.assertAlmostEqual(trip.wheel_distance_km, 10.0)
        self.assertAlmostEqual(trip.wheel_distance_corrected_km, 10.2536)
        # GPS düzeltilmiş tekerlekle birebir tutuyorsa oran tam 1,0 (eskiden ~1,025 çıkardı).
        self.assertAlmostEqual(trip.gps_wheel_ratio, 1.0)
        # Tekerlek mesafesi yoksa ya da sıfırsa oran yok.
        no_wheel = Trip.from_json({"startEpoch": 1, "endEpoch": 2, "durationSec": 1, "distanceKm": 5.0})
        self.assertIsNone(no_wheel.wheel_distance_corrected_km)
        self.assertIsNone(no_wheel.gps_wheel_ratio)
        zero = Trip.from_json(
            {"startEpoch": 1, "endEpoch": 2, "durationSec": 1, "distanceKm": 5.0, "wheelDistanceKm": 0}
        )
        self.assertIsNone(zero.gps_wheel_ratio)
        # Toplam da düzeltilmiş mesafeyi topluyor.
        summary = stats.summarize([trip, no_wheel])
        self.assertAlmostEqual(summary.total_wheel_km, 10.2536)

    def test_schema_1_record(self) -> None:
        """Şema 1'de ölçüm `seconds` alanındaydı; kayıt atılmamalı."""
        trip = Trip.from_json(
            {
                "startEpoch": 1,
                "endEpoch": 2,
                "durationSec": 1,
                "distanceKm": 1.0,
                "records": [{"kind": "0-100", "seconds": 7.4, "epoch": 5}],
            }
        )
        self.assertEqual(trip.schema_version, 1)
        self.assertAlmostEqual(trip.records[0].value, 7.4)
        self.assertEqual(trip.records[0].unit, "s")


class LoaderTests(unittest.TestCase):
    def test_merge_prefers_richer_copy(self) -> None:
        lean = Trip.from_json(
            {"startEpoch": 100, "endEpoch": 200, "durationSec": 100, "distanceKm": 5.0}
        )
        rich = Trip.from_json(
            {
                "schemaVersion": 3,
                "startEpoch": 100,
                "endEpoch": 200,
                "durationSec": 100,
                "distanceKm": 5.0,
                "energyKwh": 0.9,
                "wheelDistanceKm": 4.9,
            }
        )
        merged, duplicates = merge([[lean], [rich]])
        self.assertEqual(duplicates, 1)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].schema_version, 3)
        self.assertAlmostEqual(merged[0].energy_kwh, 0.9)

    def test_merge_sorts_ascending(self) -> None:
        older = Trip.from_json({"startEpoch": 10, "endEpoch": 20, "durationSec": 1, "distanceKm": 1})
        newer = Trip.from_json({"startEpoch": 90, "endEpoch": 99, "durationSec": 1, "distanceKm": 1})
        merged, _ = merge([[newer, older]])
        self.assertEqual([t.start_epoch for t in merged], [10, 90])

    def test_bad_file_raises(self) -> None:
        bad = ROOT / "tests" / "_gecici-bozuk.txt"
        bad.write_text("{bu json degil", encoding="utf-8")
        try:
            with self.assertRaises(TripFileError):
                read_file(bad)
        finally:
            bad.unlink()

    def test_folder_load_skips_unreadable(self) -> None:
        folder = ROOT / "tests" / "_gecici-klasor"
        folder.mkdir(exist_ok=True)
        (folder / "trips-iyi.txt").write_text(
            json.dumps([{"startEpoch": 5, "endEpoch": 6, "durationSec": 1, "distanceKm": 2.0}]),
            encoding="utf-8",
        )
        (folder / "trips-bozuk.txt").write_text("[", encoding="utf-8")
        try:
            result = load([folder])
            self.assertEqual(len(result.trips), 1)
            self.assertEqual(len(result.failures), 1)
        finally:
            for f in folder.iterdir():
                f.unlink()
            folder.rmdir()


class SourceTests(unittest.TestCase):
    """Birden çok kaynağın birikerek gösterilmesi."""

    @staticmethod
    def _source(label: str, epochs: list[int], paths: tuple[Path, ...] = ()) -> Source:
        trips = [
            Trip.from_json(
                {"startEpoch": e, "endEpoch": e + 1000, "durationSec": 1, "distanceKm": 1.0}
            )
            for e in epochs
        ]
        return Source(
            kind="file",
            label=label,
            paths=paths or (Path(label),),
            result=LoadResult(trips=trips, files=[Path(label)], failures=[], duplicates=0),
        )

    def test_sources_add_up(self) -> None:
        """Drive'ın son kayıtları + klasördeki eskiler = ikisi birden."""
        drive_gibi = self._source("drive", [300, 400])
        klasor = self._source("eski", [100, 200])
        result = combine([drive_gibi, klasor])
        self.assertEqual([t.start_epoch for t in result.trips], [100, 200, 300, 400])
        self.assertEqual(result.duplicates, 0)

    def test_overlapping_sources_count_a_trip_once(self) -> None:
        result = combine([self._source("a", [100, 200]), self._source("b", [200, 300])])
        self.assertEqual([t.start_epoch for t in result.trips], [100, 200, 300])
        self.assertEqual(result.duplicates, 1)

    def test_combine_of_nothing_is_empty(self) -> None:
        result = combine([])
        self.assertEqual(result.trips, [])
        self.assertEqual(result.files, [])
        self.assertEqual(result.duplicates, 0)

    def test_key_ignores_path_order(self) -> None:
        """Aynı dosyalar başka sırayla seçilince ikinci bir kaynak açılmamalı."""
        a = self._source("x", [1], paths=(Path("a.txt"), Path("b.txt")))
        b = self._source("x", [1], paths=(Path("b.txt"), Path("a.txt")))
        self.assertEqual(a.key, b.key)


class StatsTests(unittest.TestCase):
    def test_average_is_energy_weighted(self) -> None:
        """Düz ortalama 15,0 verirdi; enerji ağırlıklısı uzun yolculuğa yakın."""
        short = Trip.from_json(
            {"startEpoch": 1, "endEpoch": 2, "durationSec": 60, "distanceKm": 2.0, "energyKwh": 0.4}
        )  # 20 kWh/100
        long = Trip.from_json(
            {"startEpoch": 3, "endEpoch": 4, "durationSec": 60, "distanceKm": 200.0, "energyKwh": 20.0}
        )  # 10 kWh/100
        summary = stats.summarize([short, long])
        self.assertAlmostEqual(summary.avg_consumption_kwh100, 20.4 / 202.0 * 100.0)
        self.assertLess(summary.avg_consumption_kwh100, 11.0)

    def test_range_bias_is_distance_weighted(self) -> None:
        a = Trip.from_json(
            {
                "startEpoch": 1, "endEpoch": 2, "durationSec": 1,
                "distanceKm": 10.0, "rangeBiasFactor": 1.4,
            }
        )
        b = Trip.from_json(
            {
                "startEpoch": 3, "endEpoch": 4, "durationSec": 1,
                "distanceKm": 90.0, "rangeBiasFactor": 0.9,
            }
        )
        self.assertAlmostEqual(stats.average_range_bias([a, b]), (1.4 * 10 + 0.9 * 90) / 100.0)

    def test_bias_verdict_text(self) -> None:
        self.assertIn("tuttu", stats.bias_verdict(1.02))
        self.assertIn("iyimser", stats.bias_verdict(1.20))
        self.assertIn("kötümser", stats.bias_verdict(0.73))
        self.assertEqual(stats.bias_verdict(None), "—")

    def test_band_stats_cover_all_bands(self) -> None:
        trips = read_file(SAMPLE)
        bands = stats.band_stats(trips)
        self.assertEqual(len(bands), 4)
        # Örnek veride sıcaklıklar 20–33 °C: yalnızca iki üst bant dolu.
        self.assertEqual([b.trip_count for b in bands][:2], [0, 0])
        self.assertGreater(sum(b.trip_count for b in bands), 0)

    def test_by_day_groups(self) -> None:
        trips = read_file(SAMPLE)
        days = stats.by_day(trips)
        self.assertEqual(sum(d.trip_count for d in days), len(trips))
        self.assertEqual(days, sorted(days, key=lambda d: d.day))

    def test_summary_of_empty_list(self) -> None:
        summary = stats.summarize([])
        self.assertEqual(summary.trip_count, 0)
        self.assertIsNone(summary.avg_consumption_kwh100)
        self.assertIsNone(summary.first_start)


class _TempAppData:
    """`%LOCALAPPDATA%`'yı geçici klasöre çevirir: testler gerçek önbelleğe,
    imlece ya da oturum dosyasına dokunmasın."""

    def __enter__(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self._tmp.name
        return Path(self._tmp.name)

    def __exit__(self, *_exc: object) -> None:
        if self._old is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._old
        self._tmp.cleanup()


#: 2026-09-28 16:36 İstanbul — araç tarafındaki testlerle aynı yolculuk.
EPOCH = 1790602585477
EMAIL = "surucu@example.com"
UTC = timezone.utc


def _summary(epoch: int, **extra: object) -> bytes:
    body = {"schemaVersion": 3, "startEpoch": epoch, "endEpoch": epoch + 600_000,
            "durationSec": 600, "distanceKm": 5.0}
    body.update(extra)
    return json.dumps(body).encode("utf-8")


def _track_text(epoch: int = EPOCH, order: tuple[str, ...] | None = None, version: int = 1) -> str:
    rows = [
        {"t": epoch + 2000, "lat": 41.0, "lon": 29.0, "alt": 100.0, "hacc": 5.0, "vacc": 0.5,
         "gps_kmh": None, "kmh": 0.0, "kw": 0.0, "soc": 61.0, "dist_m": 0.0},
        {"t": epoch + 3000, "lat": 41.0001, "lon": 29.0001, "alt": 101.5, "hacc": 4.0, "vacc": 0.5,
         "gps_kmh": 30.2, "kmh": 31.0, "kw": 12.5, "soc": 60.99, "dist_m": 13.6},
        {"t": epoch + 4000, "lat": 41.0002, "lon": 29.0003, "alt": None, "hacc": 4.0, "vacc": None,
         "gps_kmh": 28.0, "kmh": 27.0, "kw": -8.25, "soc": 60.98, "dist_m": 32.1},
    ]
    cols = order or gps.COLUMNS
    lines = [f"# ex30-track;{version};{epoch}", ";".join(cols)]
    for row in rows:
        lines.append(";".join("" if row[c] is None else str(row[c]) for c in cols))
    return "\n".join(lines) + "\n"


def _error(code: int, reason: str = "", message: str = "") -> tuple[int, bytes]:
    errors = [{"reason": reason, "message": message}] if reason else []
    return code, json.dumps({"error": {"code": code, "message": message, "errors": errors}}).encode()


class FakeDrive:
    """Drive REST v3'ün okuma uçlarının bellekteki karşılığı.

    `HttpApi`'nin `transport`'u yerine geçiyor: istekler gerçek adres ve
    gerçek `q` sorgusu olarak geliyor, yanıtlar gerçek JSON gövdesi olarak
    dönüyor ve gerçek çözümleyiciden (`parse_files`) geçiyor. Sahte ile
    gerçek istemci arasında yalnızca HTTP yok.
    """

    def __init__(self) -> None:
        self.files: list[dict] = []
        self.clock = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
        self.page_size = 1000
        self.valid_tokens = {"t1"}
        #: Sıradaki istekler bu yanıtları alır (hata senaryoları).
        self.script: list[tuple[int, bytes]] = []
        self.list_calls: list[datetime | None] = []
        self.page_tokens: list[str | None] = []
        self.downloads: list[str] = []
        self.corrupt: set[str] = set()
        self.auth_seen: list[str] = []

    def add(self, name: str, content: bytes, created: datetime | None = None, **props: str) -> dict:
        self.clock += timedelta(seconds=10)
        match = drive.TRIP_RE.match(name)
        row = {
            "id": f"id-{len(self.files)}",
            "name": name,
            "createdTime": drive.format_time(created or self.clock),
            "size": str(len(content)),
            "md5Checksum": hashlib.md5(content).hexdigest(),
            "appProperties": {"ex30": "trip", "ex30id": name, "epoch": match.group(1),
                              "tur": "ozet" if name.endswith(".json") else "iz", **props},
            "trashed": False,
            "_content": content,
        }
        self.files.append(row)
        return row

    def add_trip(self, epoch: int, track: bool = False, created: datetime | None = None) -> None:
        self.add(drive.summary_name(epoch), _summary(epoch), created)
        if track:
            self.add(drive.track_name(epoch), gzip.compress(_track_text(epoch).encode()), created)

    def __call__(self, method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes]:
        assert method == "GET" and body is None, "Viewer Drive'a yazmaz"
        token = headers.get("Authorization", "").removeprefix("Bearer ")
        self.auth_seen.append(token)
        if self.script:
            return self.script.pop(0)
        if token not in self.valid_tokens:
            return _error(401, "authError", "Invalid Credentials")
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        if parsed.path.endswith("/drive/v3/files"):
            return self._list(params)
        match = re.fullmatch(r"/drive/v3/files/([^/]+)", parsed.path)
        if match and params.get("alt") == "media":
            for row in self.files:
                if row["id"] == urllib.parse.unquote(match.group(1)):
                    self.downloads.append(row["name"])
                    content = row["_content"]
                    return 200, content[:-3] if row["name"] in self.corrupt else content
            return _error(404, "notFound", "File not found")
        return _error(400, "badRequest", "Invalid Value")

    def _list(self, params: dict[str, str]) -> tuple[int, bytes]:
        q = params["q"]
        assert "appProperties has { key='ex30' and value='trip' }" in q and "trashed=false" in q
        assert params.get("orderBy") == "createdTime"
        since_match = re.search(r"createdTime > '([^']+)'", q)
        since = drive.parse_time(since_match.group(1)) if since_match else None
        id_match = re.search(r"key='ex30id' and value='([^']+)'", q)
        rows = [
            r for r in self.files
            if not r["trashed"]
            and (since is None or drive.parse_time(r["createdTime"]) > since)
            and (id_match is None or r["appProperties"]["ex30id"] == id_match.group(1))
        ]
        rows.sort(key=lambda r: r["createdTime"])
        if id_match is None:
            self.list_calls.append(since)
            self.page_tokens.append(params.get("pageToken"))
        start = int(params.get("pageToken", "0"))
        page = rows[start:start + self.page_size]
        payload: dict = {"files": [{k: v for k, v in r.items() if not k.startswith("_") and k != "trashed"}
                                   for r in page]}
        if start + self.page_size < len(rows):
            payload["nextPageToken"] = str(start + self.page_size)
        return 200, json.dumps(payload).encode()


class FakeTokens:
    """`drive.TokenSource`: sıradaki token'lar `refreshed` listesinden."""

    def __init__(self, token: str = "t1", refreshed: tuple[str, ...] = ()) -> None:
        self.token = token
        self.refreshed = list(refreshed)
        self.refreshes = 0
        self.forgotten = False

    def access_token(self) -> str:
        return self.token

    def refresh(self, stale: str) -> None:
        self.refreshes += 1
        if self.refreshed:
            self.token = self.refreshed.pop(0)

    def forget(self) -> None:
        self.forgotten = True


class FakePost:
    """Google'ın token ve iptal uçları: istekleri kaydedip sıradaki yanıtı verir."""

    def __init__(self, *responses: tuple[int, dict]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, data: dict[str, str]) -> tuple[int, dict]:
        self.calls.append((url, dict(data)))
        return self.responses.pop(0) if self.responses else (200, {})


def _id_token(email: str) -> str:
    """İmzasız, yalnızca gövdesi anlamlı bir id_token (email_of imzaya bakmıyor)."""
    def part(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    return f"{part({'alg': 'none'})}.{part({'email': email})}.imza"


def _api(fake: FakeDrive, tokens: FakeTokens | None = None, sleeps: list | None = None) -> drive.HttpApi:
    return drive.HttpApi(tokens or FakeTokens(), transport=fake,
                         sleep=(sleeps.append if sleeps is not None else (lambda _s: None)))


class DriveApiTests(unittest.TestCase):
    """Ağ katmanı: `files.list` çözümleme, sayfalama, `alt=media` + MD5 ve
    HTTP koduna göre hata politikası (PROTOKOL.md §4.8)."""

    def test_parse_files_skips_rows_it_does_not_understand(self) -> None:
        good = {"id": "a", "createdTime": "2026-09-29T08:00:00.000Z", "size": "12", "md5Checksum": "x",
                "appProperties": {"ex30": "trip", "ex30id": f"trip-{EPOCH}.json", "epoch": str(EPOCH), "tur": "ozet"}}
        raw = json.dumps({"nextPageToken": "p2", "files": [
            good,
            {**good, "id": "b", "appProperties": {**good["appProperties"], "tur": "iz"}},        # tür adla tutmuyor
            {**good, "id": "c", "appProperties": {**good["appProperties"], "epoch": "1"}},       # epoch adla çelişiyor
            {**good, "id": "d", "appProperties": {"ex30": "kayit", "ex30id": "trips.json"}},     # günlük dosyası
            {**good, "id": "e", "appProperties": {**good["appProperties"], "tur": "harita"}},    # bilinmeyen tür
            {"id": "f"},
            "bozuk satır",
        ]}).encode()
        files, token = drive.parse_files(raw)
        self.assertEqual(token, "p2")
        self.assertEqual([(f.id, f.epoch, f.kind, f.size) for f in files], [("a", EPOCH, "ozet", 12)])
        with self.assertRaises(drive.DriveError):
            drive.parse_files(b"<html>")
        self.assertEqual(drive.parse_files(b'{"files": []}'), ([], None))

    def test_listing_follows_every_page(self) -> None:
        fake = FakeDrive()
        fake.page_size = 2
        for k in range(5):
            fake.add_trip(EPOCH + k * 60_000)
        records = _api(fake).list_trips(None)
        self.assertEqual([r.epoch for r in records], [EPOCH + k * 60_000 for k in range(5)])
        self.assertEqual(fake.page_tokens, [None, "2", "4"])

    def test_query_uses_rfc3339_cursor(self) -> None:
        since = datetime(2026, 9, 29, 8, 7, 33, 123000, tzinfo=UTC)
        self.assertTrue(drive.trips_query(since).endswith("and createdTime > '2026-09-29T08:07:33.123Z'"))
        self.assertEqual(drive.parse_time("2026-09-29T08:07:33.123Z"), since)
        self.assertEqual(drive.trips_query(None), drive.TRIP_QUERY)
        self.assertIsNone(drive.parse_time("dün"))

    def test_download_checks_md5(self) -> None:
        fake = FakeDrive()
        fake.add_trip(EPOCH)
        api = _api(fake)
        record = api.list_trips(None)[0]
        self.assertEqual(api.download(record), _summary(EPOCH))
        fake.corrupt.add(record.ex30id)
        with self.assertRaises(drive.DriveError) as caught:
            api.download(record)
        self.assertIn("MD5 tutmadı", str(caught.exception))

    def test_401_refreshes_once_and_retries(self) -> None:
        fake = FakeDrive()
        fake.add_trip(EPOCH)
        fake.valid_tokens = {"t2"}
        tokens = FakeTokens("t1", refreshed=("t2",))
        self.assertEqual(len(_api(fake, tokens).list_trips(None)), 1)
        self.assertEqual((tokens.refreshes, fake.auth_seen), (1, ["t1", "t2"]))
        self.assertFalse(tokens.forgotten)

    def test_401_after_refresh_means_sign_in_again(self) -> None:
        fake = FakeDrive()
        fake.valid_tokens = {"hiçbiri"}
        tokens = FakeTokens("t1", refreshed=("t2",))
        with self.assertRaises(drive.AuthError) as caught:
            _api(fake, tokens).list_trips(None)
        self.assertTrue(caught.exception.relogin)
        self.assertEqual(tokens.refreshes, 1)  # sonsuz yenileme döngüsü yok
        self.assertTrue(tokens.forgotten)

    def test_insufficient_permissions_means_sign_in_again(self) -> None:
        fake = FakeDrive()
        fake.script = [_error(403, "insufficientPermissions", "Request had insufficient authentication scopes.")]
        tokens = FakeTokens()
        with self.assertRaises(drive.AuthError) as caught:
            _api(fake, tokens).list_trips(None)
        self.assertEqual(caught.exception.key, "drive.err.no_permission")
        self.assertTrue(tokens.forgotten)

    def test_rate_limit_backs_off(self) -> None:
        fake = FakeDrive()
        fake.add_trip(EPOCH)
        fake.script = [_error(429, "rateLimitExceeded"), _error(403, "userRateLimitExceeded")]
        sleeps: list[float] = []
        self.assertEqual(len(_api(fake, sleeps=sleeps).list_trips(None)), 1)
        self.assertEqual(sleeps, [1.0, 2.0])

        fake.script = [_error(403, "rateLimitExceeded")] * 4
        with self.assertRaises(drive.DriveError) as caught:
            _api(fake).list_trips(None)
        self.assertEqual(caught.exception.key, "drive.err.rate_limit")
        self.assertFalse(caught.exception.relogin)

    def test_missing_file_and_other_errors(self) -> None:
        fake = FakeDrive()
        gone = drive.DriveFile(id="yok", ex30id=drive.summary_name(EPOCH), epoch=EPOCH, kind="ozet")
        with self.assertRaises(drive.DriveError) as caught:
            _api(fake).download(gone)
        self.assertEqual(caught.exception.key, "drive.err.not_found")
        fake.script = [_error(400, "badRequest", "Invalid Value")]
        with self.assertRaises(drive.DriveError) as caught:
            _api(fake).list_trips(None)
        self.assertEqual(str(caught.exception), "Drive 400 döndü: Invalid Value")


class SyncTests(unittest.TestCase):
    """Artımlı eşitleme (PROTOKOL.md §4): imleç, örtüşme, tekleme, günlük tam
    tarama. Kurallar telefondaki eşitleme motoruyla aynı; iki istemci aynı
    Drive'dan aynı sonucu çıkarmalı."""

    T0 = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)

    def setUp(self) -> None:
        self._appdata = _TempAppData()
        self._appdata.__enter__()
        self.cache = drive.AccountCache(EMAIL)
        self.fake = FakeDrive()
        self.api = _api(self.fake)

    def tearDown(self) -> None:
        self._appdata.__exit__(None, None, None)

    def sync(self, at: datetime | None = None, **kwargs: object) -> drive.SyncResult:
        return drive.sync(self.api, self.cache, now=at or self.T0, **kwargs)

    def test_cache_layout_follows_istanbul_month_per_account(self) -> None:
        # 2026-09-30 21:30 UTC = 1 Ekim 00:30 İstanbul: ay klasörü 10 olmalı.
        epoch = int(datetime(2026, 9, 30, 21, 30, tzinfo=UTC).timestamp() * 1000)
        path = self.cache.summary_path(epoch)
        self.assertEqual(path.parent.parts[-2:], ("2026", "10"))
        self.assertEqual(path.name, f"trip-{epoch}.json")
        self.assertEqual(path.parts[-6:-3], ("hesaplar", EMAIL, "yolculuklar"))
        self.assertNotEqual(drive.AccountCache("baska@example.com").root, self.cache.root)

    def test_first_sync_downloads_summaries_and_sets_cursor(self) -> None:
        for k in range(3):
            self.fake.add_trip(EPOCH + k * 60_000, track=(k != 1))
        steps: list[tuple[int, int]] = []
        result = self.sync(progress=lambda d, n: steps.append((d, n)))
        self.assertEqual(self.fake.list_calls, [None])
        self.assertEqual((result.new_trips, result.local, result.listed), (3, 3, 5))
        self.assertTrue(result.full_scan and result.cursor_advanced)
        self.assertEqual((steps[0], steps[-1]), ((0, 3), (3, 3)))
        state = self.cache.load_state()
        self.assertEqual(state.cursor, self.fake.files[-1]["createdTime"])
        self.assertEqual(result.last_full, self.T0)
        self.assertEqual(set(state.tracks), {EPOCH, EPOCH + 120_000})
        # Özetler iz İNDİRİLMEDEN geldi; izler gerekince iniyor.
        self.assertTrue(all(n.endswith(".json") for n in self.fake.downloads))
        self.assertEqual(self.cache.summary_path(EPOCH).read_bytes(), _summary(EPOCH))

    def test_next_sync_asks_from_cursor_minus_five_minutes(self) -> None:
        self.fake.add_trip(EPOCH)
        self.sync()
        cursor = drive.parse_time(self.cache.load_state().cursor)
        self.fake.downloads.clear()
        result = self.sync(self.T0 + timedelta(hours=1))
        self.assertEqual(self.fake.list_calls[-1], cursor - timedelta(minutes=5))
        self.assertFalse(result.full_scan)
        # Örtüşmede eski özet yine listede; yerelde olduğu için inmiyor.
        self.assertEqual((result.listed, result.new_trips, self.fake.downloads), (1, 0, []))

    def test_late_file_inside_overlap_is_not_missed(self) -> None:
        """Drive listesi yeni dosyayı gecikmeyle gösterebiliyor: imleçten
        2 dk ÖNCE oluşturulmuş ama ilk listede görünmemiş dosya."""
        self.fake.add_trip(EPOCH)
        self.sync()
        cursor = drive.parse_time(self.cache.load_state().cursor)
        self.fake.add_trip(EPOCH + 60_000, created=cursor - timedelta(minutes=2))
        result = self.sync(self.T0 + timedelta(hours=1))
        self.assertEqual(result.new_trips, 1)
        # İmleç geri gitmedi: yeni dosya imleçten eski.
        self.assertEqual(drive.parse_time(self.cache.load_state().cursor), cursor)

    def test_same_file_twice_in_a_listing_is_downloaded_once(self) -> None:
        self.fake.add_trip(EPOCH)
        self.fake.files.append(dict(self.fake.files[0]))  # sayfa kayması: aynı satır iki kez
        result = self.sync()
        self.assertEqual((result.listed, self.fake.downloads), (1, [drive.summary_name(EPOCH)]))

    def test_failed_download_keeps_cursor_and_is_retried(self) -> None:
        for k in range(3):
            self.fake.add_trip(EPOCH + k * 60_000)
        bad = drive.summary_name(EPOCH + 60_000)
        self.fake.corrupt.add(bad)
        result = self.sync()
        self.assertFalse(result.cursor_advanced)
        self.assertEqual((result.new_trips, result.failed), (2, 1))
        self.assertIn("MD5 tutmadı", result.errors[0])
        state = self.cache.load_state()
        self.assertIsNone(state.cursor)
        self.assertIsNone(state.last_full)
        # Bozuk inen dosya diske hiç yazılmadı; inenler duruyor.
        self.assertFalse(self.cache.summary_path(EPOCH + 60_000).exists())
        self.assertEqual(self.cache.known_summaries(), {EPOCH, EPOCH + 120_000})

        self.fake.corrupt.clear()
        self.fake.downloads.clear()
        retry = self.sync()
        self.assertEqual(self.fake.downloads, [bad])
        self.assertTrue(retry.cursor_advanced)
        self.assertEqual(retry.local, 3)

    def test_listing_error_changes_nothing(self) -> None:
        self.fake.add_trip(EPOCH)
        self.sync()
        before = self.cache.state_path.read_bytes()
        self.fake.script = [_error(500, "backendError", "x")] * 4
        with self.assertRaises(drive.DriveError):
            self.sync(self.T0 + timedelta(hours=1))
        self.assertEqual(self.cache.state_path.read_bytes(), before)

    def test_corrupt_remote_never_overwrites_what_is_here(self) -> None:
        self.fake.add_trip(EPOCH, track=True)
        self.sync()
        track = drive.download_track(self.api, self.cache, EPOCH)
        kept_summary = self.cache.summary_path(EPOCH).read_bytes()
        kept_track = track.read_bytes()
        self.fake.corrupt.update({drive.summary_name(EPOCH), drive.track_name(EPOCH)})
        self.fake.add_trip(EPOCH + 60_000, track=True)
        self.fake.corrupt.update({drive.summary_name(EPOCH + 60_000), drive.track_name(EPOCH + 60_000)})
        self.fake.downloads.clear()
        result = self.sync(full=True)
        self.assertEqual(result.failed, 1)
        self.assertEqual(self.fake.downloads, [drive.summary_name(EPOCH + 60_000)])
        self.assertEqual(self.cache.summary_path(EPOCH).read_bytes(), kept_summary)
        self.assertEqual(drive.download_track(self.api, self.cache, EPOCH).read_bytes(), kept_track)
        with self.assertRaises(drive.DriveError):
            drive.download_track(self.api, self.cache, EPOCH + 60_000)
        self.assertFalse(self.cache.track_path(EPOCH + 60_000).exists())
        self.assertFalse(self.cache.summary_path(EPOCH + 60_000).exists())

    def test_full_scan_decision(self) -> None:
        state = drive.SyncState()
        self.assertTrue(drive.needs_full_scan(state, self.T0))  # ilk eşitleme
        state = drive.SyncState(cursor="2026-09-29T08:00:00.000Z", last_full=drive.format_time(self.T0))
        self.assertFalse(drive.needs_full_scan(state, self.T0 + timedelta(hours=23, minutes=59)))
        self.assertTrue(drive.needs_full_scan(state, self.T0 + timedelta(days=1)))
        self.assertTrue(drive.needs_full_scan(state, self.T0 - timedelta(hours=1)))  # saat geri alındı
        self.assertTrue(drive.needs_full_scan(drive.SyncState(cursor=state.cursor), self.T0))

    def test_daily_and_requested_full_scans(self) -> None:
        """İmlecin gerisinde kalan dosya ancak tam listede görünür (Drive'da
        sürüm 2'deki `toplam` yok)."""
        self.fake.add_trip(EPOCH)
        self.sync()
        cursor = drive.parse_time(self.cache.load_state().cursor)
        self.fake.add_trip(EPOCH + 60_000, created=cursor - timedelta(hours=3))

        hour = self.sync(self.T0 + timedelta(hours=1))
        self.assertEqual((hour.full_scan, hour.new_trips), (False, 0))
        self.assertEqual(hour.last_full, self.T0)

        asked = self.sync(self.T0 + timedelta(hours=2), full=True)
        self.assertEqual(self.fake.list_calls[-1], None)
        self.assertEqual((asked.full_scan, asked.new_trips), (True, 1))
        self.assertEqual(asked.last_full, self.T0 + timedelta(hours=2))

        self.fake.add_trip(EPOCH + 120_000, created=cursor - timedelta(hours=3))
        self.sync(self.T0 + timedelta(hours=3))
        self.assertIsNotNone(self.fake.list_calls[-1])
        daily = self.sync(self.T0 + timedelta(days=1, hours=2))
        self.assertEqual(self.fake.list_calls[-1], None)
        self.assertEqual((daily.full_scan, daily.new_trips, daily.local), (True, 1, 3))

    def test_full_scan_forgets_trashed_tracks(self) -> None:
        self.fake.add_trip(EPOCH, track=True)
        self.sync()
        self.assertFalse(drive.track_known_missing(self.cache, EPOCH))
        self.fake.files[1]["trashed"] = True
        self.sync(self.T0 + timedelta(hours=1))
        self.assertFalse(drive.track_known_missing(self.cache, EPOCH))  # artımlı liste silineni bilemez
        self.sync(self.T0 + timedelta(hours=2), full=True)
        self.assertTrue(drive.track_known_missing(self.cache, EPOCH))

    def test_track_download_and_missing_track(self) -> None:
        self.fake.add_trip(EPOCH, track=True)
        self.fake.add_trip(EPOCH + 60_000)
        # Hiç eşitlenmeden: izin olmadığı bilinmiyor, `ex30id` ile soruluyor.
        self.assertFalse(drive.track_known_missing(self.cache, EPOCH + 60_000))
        self.assertIsNone(drive.download_track(self.api, self.cache, EPOCH + 60_000))
        path = drive.download_track(self.api, self.cache, EPOCH)
        self.assertEqual(gzip.decompress(path.read_bytes()).decode(), _track_text(EPOCH))
        self.assertEqual(self.fake.list_calls, [])  # tam liste değil, tek dosya arandı

        self.sync()
        self.assertTrue(drive.track_known_missing(self.cache, EPOCH + 60_000))
        self.assertFalse(drive.track_known_missing(self.cache, EPOCH))
        self.fake.downloads.clear()
        self.assertEqual(drive.download_track(self.api, self.cache, EPOCH), path)
        self.assertEqual(self.fake.downloads, [])  # önbellekten; dosyalar değişmez

    def test_summary_that_does_not_match_its_name_is_rejected(self) -> None:
        self.fake.add(drive.summary_name(EPOCH), _summary(EPOCH + 1))
        result = self.sync()
        self.assertEqual(result.failed, 1)
        self.assertEqual(self.cache.known_summaries(), set())

    def test_cache_folder_loads_as_one_source(self) -> None:
        self.fake.add_trip(EPOCH)
        self.fake.add_trip(EPOCH + 40 * 86_400_000)  # başka ay klasörü
        result = self.sync()
        loaded = load([result.path])
        self.assertEqual([t.start_epoch for t in loaded.trips], [EPOCH, EPOCH + 40 * 86_400_000])
        self.assertEqual(loaded.failures, [])


class AuthTests(unittest.TestCase):
    """Google girişi (PROTOKOL.md §1): izin kutusu tuzağı, token saklama,
    yenileme, çıkış. Ağ yok: token ucu `FakePost`, tarayıcı bir thread."""

    CLIENT = auth.Client("istemci", "sir")

    def setUp(self) -> None:
        self._appdata = _TempAppData()
        self.home = self._appdata.__enter__()

    def tearDown(self) -> None:
        self._appdata.__exit__(None, None, None)

    @staticmethod
    def _tokens(scope: str = f"{auth.SCOPE_DRIVE} openid email", refresh: str = "yenileme-1") -> dict:
        return {"access_token": "erisim-1", "expires_in": 3599, "refresh_token": refresh,
                "scope": scope, "id_token": _id_token(EMAIL)}

    def _sign_in(self, post: FakePost) -> tuple[auth.Session | Exception, list[str]]:
        """Tarayıcıyı taklit ederek girişi baştan sona çalıştırır."""
        opened: list[str] = []

        def browser(url: str) -> bool:
            opened.append(url)
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            back = f"{query['redirect_uri']}/?code=kod-1&state={query['state']}"
            threading.Thread(target=lambda: urllib.request.urlopen(back, timeout=5).read(), daemon=True).start()
            return True

        try:
            return auth.sign_in(threading.Event(), client=self.CLIENT, open_browser=browser,
                                post=post, timeout_s=10), opened
        except Exception as e:
            return e, opened

    def test_sign_in_without_the_drive_box_is_refused(self) -> None:
        result, _ = self._sign_in(FakePost((200, self._tokens(scope="openid email https://www.googleapis.com/auth/userinfo.email"))))
        self.assertIsInstance(result, drive.AuthError)
        self.assertEqual(result.key, "auth.err.no_drive")
        self.assertIn("Drive kutusunu", str(result))
        self.assertFalse(auth.account_path().exists())
        with self.assertRaises(drive.AuthError):
            auth.require_drive({"scope": ""})
        auth.require_drive({"scope": f"openid {auth.SCOPE_DRIVE}"})

    def test_sign_in_uses_pkce_and_stores_the_session(self) -> None:
        post = FakePost((200, self._tokens()))
        session, opened = self._sign_in(post)
        self.assertIsInstance(session, auth.Session)
        self.assertEqual(session.email, EMAIL)
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(opened[0]).query))
        self.assertEqual(query["scope"], auth.SCOPES)
        self.assertTrue(query["redirect_uri"].startswith("http://127.0.0.1:"))
        _url, form = post.calls[0]
        self.assertEqual((form["code"], form["grant_type"]), ("kod-1", "authorization_code"))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest())
        self.assertEqual(challenge.rstrip(b"=").decode(), query["code_challenge"])
        # Access token bellekte, yenileme istenmeden kullanılıyor.
        self.assertEqual(session.access_token(), "erisim-1")
        self.assertEqual(len(post.calls), 1)
        loaded = auth.load_session()
        self.assertEqual((loaded.email, loaded._refresh_token), (EMAIL, "yenileme-1"))

    @unittest.skipUnless(sys.platform == "win32", "DPAPI yalnızca Windows'ta")
    def test_refresh_token_is_encrypted_with_dpapi(self) -> None:
        auth.Session(EMAIL, "gizli-yenileme-anahtari").save()
        stored = auth.account_path().read_text(encoding="utf-8")
        self.assertEqual(json.loads(stored)["koruma"], "dpapi")
        self.assertNotIn("gizli-yenileme-anahtari", stored)
        self.assertNotIn(base64.b64encode(b"gizli-yenileme-anahtari").decode(), stored)
        self.assertEqual(auth.load_session()._refresh_token, "gizli-yenileme-anahtari")

    def test_refresh_and_invalid_grant(self) -> None:
        post = FakePost(
            (200, {"access_token": "erisim-2", "expires_in": 3599, "scope": f"openid {auth.SCOPE_DRIVE}"}),
            (400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}),
        )
        auth.Session(EMAIL, "yenileme-1").save()
        session = auth.load_session(post=post)
        session._client = self.CLIENT
        self.assertEqual(session.access_token(), "erisim-2")
        self.assertEqual(post.calls[0][1]["grant_type"], "refresh_token")
        session.refresh("başka-token")  # başka thread zaten yeniledi: istek yok
        self.assertEqual(len(post.calls), 1)
        with self.assertRaises(drive.AuthError) as caught:
            session.refresh("erisim-2")
        self.assertEqual(caught.exception.key, "auth.err.expired")
        self.assertTrue(session.dead)
        self.assertFalse(auth.account_path().exists())
        self.assertIsNone(auth.load_session())

    def test_refresh_without_drive_scope_drops_the_token(self) -> None:
        post = FakePost((200, {"access_token": "erisim-2", "expires_in": 3599, "scope": "openid email"}))
        auth.Session(EMAIL, "yenileme-1").save()
        session = auth.Session(EMAIL, "yenileme-1", client=self.CLIENT, post=post)
        with self.assertRaises(drive.AuthError):
            session.access_token()
        self.assertFalse(auth.account_path().exists())

    def test_dead_session_does_not_delete_someone_elses_token(self) -> None:
        auth.Session("yeni@example.com", "yenileme-2").save()
        auth.Session(EMAIL, "yenileme-1").forget()
        self.assertEqual(auth.load_session().email, "yeni@example.com")

    def test_sign_out_clears_only_that_account(self) -> None:
        session = auth.Session(EMAIL, "yenileme-1")
        session.save()
        mine, other = drive.AccountCache(EMAIL), drive.AccountCache("baska@example.com")
        for cache in (mine, other):
            drive._write_atomic(cache.summary_path(EPOCH), _summary(EPOCH))
            cache.save_state(drive.SyncState(cursor="2026-09-29T08:00:00.000Z"))
        post = FakePost()
        auth.sign_out(session, post=post, wait=True)
        self.assertFalse(mine.root.exists())
        self.assertFalse(auth.account_path().exists())
        self.assertEqual(other.known_summaries(), {EPOCH})
        self.assertEqual(post.calls, [(auth.REVOKE_URL, {"token": "yenileme-1"})])
        self.assertTrue(session.dead)

    def test_client_from_properties(self) -> None:
        path = self.home / "oauth.properties"
        path.write_text("# yorum\ncarClientId=a\ndesktopClientId = masaustu\ndesktopClientSecret=sir\n", encoding="utf-8")
        self.assertEqual(auth.read_properties(path), auth.Client("masaustu", "sir"))
        path.write_text("desktopClientId=masaustu\n", encoding="utf-8")
        self.assertIsNone(auth.read_properties(path))


class MigrationTests(unittest.TestCase):
    def test_version_2_settings_are_removed_once(self) -> None:
        """PROTOKOL.md §4.1: adres + okuma anahtarı, imleç ve sürüm 2 önbelleği
        gidiyor; dil ayarı ve hesap önbellekleri kalıyor."""
        with _TempAppData():
            root = drive.config_dir()
            (root / "yolculuklar" / "2026" / "09").mkdir(parents=True)
            (root / "yolculuklar" / "2026" / "09" / f"trip-{EPOCH}.json").write_bytes(_summary(EPOCH))
            (root / "indirilen").mkdir()
            (root / "indirilen" / "trips.json").write_text("[]", encoding="utf-8")
            (root / "drive.json").write_text('{"url": "https://s/exec", "secret": "oku"}', encoding="utf-8")
            (root / "esitleme.json").write_text('{"sunucuZamani": 1}', encoding="utf-8")
            settings.save(language="en")
            cache = drive.AccountCache(EMAIL)
            drive._write_atomic(cache.summary_path(EPOCH), _summary(EPOCH))

            self.assertTrue(drive.migrate_v2())
            for name in drive.LEGACY_ENTRIES:
                self.assertFalse((root / name).exists(), name)
            self.assertEqual(settings.load(), {"language": "en"})
            self.assertEqual(cache.known_summaries(), {EPOCH})
            self.assertFalse(drive.migrate_v2())  # ikinci açılışta not yok

    def test_nothing_to_migrate_on_a_fresh_install(self) -> None:
        with _TempAppData():
            self.assertFalse(drive.migrate_v2())


class LoaderProtocol2Tests(unittest.TestCase):
    def test_single_summary_object_is_one_trip(self) -> None:
        """Özetin kendi `records` alanı (performans ölçümleri) yolculuk listesi
        sanılmamalı."""
        folder = ROOT / "tests" / "_gecici-ozet"
        folder.mkdir(exist_ok=True)
        path = folder / f"trip-{EPOCH}.json"
        path.write_bytes(_summary(EPOCH, records=[{"kind": "0-100", "value": 6.1, "unit": "s", "epoch": EPOCH + 5}]))
        try:
            trips = read_file(path)
            self.assertEqual(len(trips), 1)
            self.assertEqual(trips[0].start_epoch, EPOCH)
            self.assertEqual(trips[0].records[0].kind, "0-100")
            self.assertEqual(len(load([folder]).trips), 1)
        finally:
            path.unlink()
            folder.rmdir()


class TrackTests(unittest.TestCase):
    def test_parses_track(self) -> None:
        track = gps.parse(_track_text())
        self.assertEqual((track.version, track.start_epoch, track.rows), (1, EPOCH, 3))
        self.assertEqual(track.get("kw"), (0.0, 12.5, -8.25))
        # Boş alan None; sıfıra çevrilmez.
        self.assertEqual(track.get("gps_kmh")[0], None)
        self.assertEqual(track.get("alt"), (100.0, 101.5, None))
        self.assertTrue(track.has_position)

    def test_columns_are_read_by_name(self) -> None:
        shuffled = ("dist_m", "kw", "t", "lon", "lat", "soc", "kmh", "alt", "hacc", "vacc", "gps_kmh")
        normal = gps.parse(_track_text())
        moved = gps.parse(_track_text(order=shuffled))
        for name in gps.COLUMNS:
            self.assertEqual(moved.get(name), normal.get(name), name)
        # Bilinmeyen sütun okunmayı düşürmez; olmayan sütun "hep boş".
        lines = _track_text().split("\n")
        lines[1] += ";yeni_sutun"
        lines[2] += ";7"
        extra = gps.parse("\n".join(lines))
        self.assertEqual(extra.get("yeni_sutun"), (7.0, None, None))
        self.assertEqual(extra.get("olmayan"), (None, None, None))

    def test_unknown_version_is_reported(self) -> None:
        with self.assertRaises(gps.TrackError) as caught:
            gps.parse(_track_text(version=2))
        self.assertIn("sürüm 2", str(caught.exception))
        i18n.set_language("en")
        try:
            self.assertIn("version 2", str(caught.exception))
        finally:
            i18n.set_language("tr")

    def test_bad_header_and_wrong_trip(self) -> None:
        with self.assertRaises(gps.TrackError):
            gps.parse("t;lat;lon\n1;2;3\n")
        with self.assertRaises(gps.TrackError):
            gps.parse(f"# ex30-track;1;{EPOCH}\n")
        with self.assertRaises(gps.TrackError):
            gps.parse(_track_text(), expected_epoch=EPOCH + 1)

    def test_reads_gzip_file_and_falls_back_to_positions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"trip-{EPOCH}.csv.gz"
            cols = tuple(c for c in gps.COLUMNS if c != "dist_m")
            path.write_bytes(gzip.compress(_track_text(order=cols).encode()))
            track = gps.read(path, expected_epoch=EPOCH)
        self.assertFalse(track.has("dist_m"))
        dist = track.distance_m()
        self.assertEqual(dist[0], 0.0)
        self.assertAlmostEqual(dist[1], 13.6, delta=0.5)  # 0,0001° enlem+boylam ≈ 13,6 m

    def test_csv_follows_language(self) -> None:
        track = gps.parse(_track_text())
        buffer = io.StringIO()
        gps.write_csv(track, buffer)
        lines = buffer.getvalue().splitlines()
        self.assertEqual(lines[0].split(";")[:3], ["Zaman", "Enlem", "Boylam"])
        cells = lines[3].split(";")
        self.assertEqual(cells[1], "41,000200")
        self.assertEqual(cells[5], "")      # vacc boştu
        self.assertEqual(cells[8], "-8,25")
        i18n.set_language("en")
        try:
            buffer = io.StringIO()
            gps.write_csv(track, buffer)
            cells = buffer.getvalue().splitlines()[3].split(",")
            self.assertEqual((cells[1], cells[8]), ("41.000200", "-8.25"))
            self.assertRegex(cells[0], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        finally:
            i18n.set_language("tr")


class RouteChartTests(unittest.TestCase):
    def tearDown(self) -> None:
        i18n.set_language("tr")

    @staticmethod
    def _long_track() -> "gps.Track":
        lines = [f"# ex30-track;1;{EPOCH}", ";".join(gps.COLUMNS)]
        for i in range(400):
            kw = -12.0 if 150 < i < 220 else 8.0 + (i % 7)
            alt = "" if i % 50 == 0 else f"{100 + i * 0.1:.1f}"
            lines.append(f"{EPOCH + i * 1000};{41 + i * 1e-4:.6f};{29 + i * 2e-4:.6f};{alt};4;1;"
                         f"{40 + i % 9};{41 + i % 9};{kw:.2f};{80 - i * 0.01:.2f};{i * 11.0:.1f}")
        return gps.parse("\n".join(lines))

    def test_route_draws_in_both_languages(self) -> None:
        """Rota sekmesi dolu, boş ve eksik veriyle, iki dilde ve her renk
        seçeneğiyle gerçekten PNG'ye çizilmeli."""
        full = self._long_track()
        no_position = gps.parse(_track_text(order=("t", "alt", "kmh", "kw", "dist_m")))
        empty = gps.parse(f"# ex30-track;1;{EPOCH}\n" + ";".join(gps.COLUMNS) + "\n")
        cases = {"dolu": full, "kısa": gps.parse(_track_text()), "konumsuz": no_position,
                 "boş": empty, "yok": None}
        for code in i18n.LANGUAGES:
            i18n.set_language(code)
            for name, track in cases.items():
                for color in charts.ROUTE_COLORS:
                    with self.subTest(language=code, track=name, color=color):
                        fig = Figure(figsize=(9, 6), dpi=60, layout="constrained")
                        charts.draw_route(fig, track, color, message=i18n.t("route.no_track"))
                        fig.savefig(io.BytesIO(), format="png")

    def test_profiles_share_the_distance_axis_and_zoom_marks_the_map(self) -> None:
        fig = Figure(figsize=(9, 6), dpi=60, layout="constrained")
        charts.draw_route(fig, self._long_track(), "power")
        ax_map, ax_alt, ax_speed, ax_kw = fig.axes[:4]
        highlight = ax_map.lines[-1]
        self.assertEqual(len(highlight.get_xdata()), 0)
        ax_kw.set_xlim(1.0, 2.0)
        self.assertEqual(ax_alt.get_xlim(), (1.0, 2.0))
        self.assertEqual(ax_speed.get_xlim(), (1.0, 2.0))
        self.assertGreater(len(highlight.get_xdata()), 50)
        full = (0.0, 399 * 11.0 / 1000.0)
        ax_alt.set_xlim(*full)
        self.assertEqual(len(highlight.get_xdata()), 0)

    def test_route_aspect_is_corrected_for_latitude(self) -> None:
        fig = Figure(figsize=(9, 6), dpi=60, layout="constrained")
        charts.draw_route(fig, self._long_track(), "speed")
        self.assertAlmostEqual(fig.axes[0].get_aspect(), 1 / math.cos(math.radians(41.02)), places=2)

    def test_smoothing_skips_missing_values(self) -> None:
        values = np.array([10.0, np.nan, 10.0, 10.0, 40.0])
        smooth = charts._smooth(values, 3)
        self.assertTrue(np.isnan(smooth[1]))
        self.assertAlmostEqual(smooth[0], 10.0)  # eksik nokta sıfır sayılmadı
        self.assertAlmostEqual(smooth[3], 20.0)


class I18nTests(unittest.TestCase):
    """İki dilin tutarlılığı ve dile bağlı biçimler.

    Eksik çeviri ya da yer tutucusu tutmayan bir metin çalışma anında `KeyError`
    ile bir diyaloğu düşürürdü; burada, derlemeden önce yakalanıyor.
    """

    def tearDown(self) -> None:
        i18n.set_language("tr")

    # --- Tablolar ------------------------------------------------------------

    @staticmethod
    def _fields(template: str) -> set[str]:
        """Şablondaki yer tutucu adları; `{n|a|b}` çoğul biçimi de sayılıyor."""
        names = {m.group(1) for m in i18n.PLURAL.finditer(template)}
        plain = i18n.PLURAL.sub("", template)
        names.update(
            field.split(".")[0].split("[")[0]
            for _text, field, _spec, _conv in string.Formatter().parse(plain)
            if field
        )
        return names

    def test_tables_have_the_same_keys(self) -> None:
        tr_keys, en_keys = set(lang_tr.STRINGS), set(lang_en.STRINGS)
        self.assertEqual(sorted(tr_keys - en_keys), [], "İngilizcede eksik")
        self.assertEqual(sorted(en_keys - tr_keys), [], "Türkçede fazla/eksik")

    def test_placeholders_match(self) -> None:
        for key, tr_text in lang_tr.STRINGS.items():
            with self.subTest(key=key):
                self.assertEqual(self._fields(tr_text), self._fields(lang_en.STRINGS[key]))

    def test_every_key_used_in_code_exists(self) -> None:
        """Kodda düz yazılmış her anahtar tabloda olmalı; yazım hatası
        `t()`'nin anahtarı aynen göstermesiyle sonuçlanırdı."""
        pattern = re.compile(
            r'(?:\bt|i18n\.t|TripFileError|DriveError|AuthError|TrackError)\(\s*"([a-z0-9_.\-]+)"'
        )
        used: set[str] = set()
        for path in (ROOT / "ex30trips").glob("*.py"):
            used.update(pattern.findall(path.read_text(encoding="utf-8")))
        # Veriden türeyen anahtarlar: sekme adları, dönemler, ölçüm türleri,
        # kaynak türleri, menzil kararları.
        used.update(key for key, _fn in charts.CHARTS)
        used.update(key for key, _days in app_module.PERIODS)
        used.update(f"perf.{kind}" for kind in ("0-100", "0-60", "80-120", "100-0"))
        used.update(f"source.kind.{kind}" for kind in ("file", "folder", "sample", "drive", "cli"))
        used.update(f"bias.{kind}" for kind in ("accurate", "optimistic", "pessimistic"))
        used.update(f"route.color.{key}" for key in charts.ROUTE_COLORS)
        used.update(key for _name, key, _decimals in gps.EXPORT)
        used.add("tab.route")
        self.assertGreater(len(used), 150)
        missing = sorted(k for k in used if not i18n.has(k))
        self.assertEqual(missing, [])

    def test_unknown_language_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            i18n.set_language("de")
        self.assertEqual(i18n.language(), "tr")

    # --- Biçimler ------------------------------------------------------------

    def test_numbers(self) -> None:
        self.assertEqual(i18n.num(1234.56, 1), "1.234,6")
        self.assertEqual(i18n.pct(33.4), "%33")
        i18n.set_language("en")
        self.assertEqual(i18n.num(1234.56, 1), "1,234.6")
        self.assertEqual(i18n.pct(33.4), "33%")
        self.assertEqual(i18n.num(None), "—")

    def test_dates_do_not_depend_on_os_locale(self) -> None:
        when = datetime(2026, 9, 15, 8, 2)
        self.assertEqual(i18n.date_time(when), "15.09.2026 08:02")
        self.assertEqual(i18n.axis_label(when, "day"), "15.09")
        i18n.set_language("en")
        self.assertEqual(i18n.date_time(when), "15 Sep 2026 08:02")
        self.assertEqual(i18n.axis_label(when, "day"), "15 Sep")
        self.assertEqual(i18n.axis_label(when, "month"), "Sep 26")
        self.assertEqual(i18n.axis_label(when, "time"), "08:02")

    def test_durations_and_units(self) -> None:
        self.assertEqual(i18n.duration(4028), "1 sa 07 dk")
        self.assertEqual(i18n.duration(360), "6 dk 00 sn")
        self.assertEqual(i18n.t("unit.speed"), "km/s")
        i18n.set_language("en")
        self.assertEqual(i18n.duration(4028), "1 h 07 min")
        self.assertEqual(i18n.duration(360), "6 min 00 s")
        self.assertEqual(i18n.duration(360, seconds=False), "6 min")
        # Türkçedeki km/s "saat" demek; İngilizcede saniye okunurdu.
        self.assertEqual(i18n.t("unit.speed"), "km/h")

    def test_plural_forms(self) -> None:
        i18n.set_language("en")
        self.assertEqual(i18n.t("files.trips", n=1), "1 trip")
        self.assertEqual(i18n.t("files.trips", n=5), "5 trips")
        self.assertEqual(i18n.t("files.trips", n=0), "0 trips")
        text = i18n.t("status.added", label="x", fresh=1, sources=2, total=7)
        self.assertIn("1 new trip added", text)
        self.assertIn("2 sources", text)

    def test_csv_follows_language(self) -> None:
        when = datetime(2026, 9, 15, 8, 2, 5)
        self.assertEqual((i18n.csv_delimiter(), i18n.csv_number(14.017, 2)), (";", "14,02"))
        self.assertEqual(i18n.csv_datetime(when), "15.09.2026 08:02:05")
        i18n.set_language("en")
        self.assertEqual((i18n.csv_delimiter(), i18n.csv_number(14.017, 2)), (",", "14.02"))
        self.assertEqual(i18n.csv_datetime(when), "2026-09-15 08:02:05")
        self.assertEqual(i18n.csv_number(None, 2), "")

    # --- Metin üreten modüller -----------------------------------------------

    def test_model_and_stats_text_in_english(self) -> None:
        trip = max(read_file(SAMPLE), key=lambda t: t.distance_km)
        i18n.set_language("en")
        self.assertEqual(trip.records[0].label, "0–60 km/h")
        self.assertEqual(trip.records[0].pretty(), "8.90 s")
        self.assertEqual(trip.duration_text(), "1 h 07 min")
        self.assertEqual(stats.bias_verdict(0.73), "0.73 — 27% pessimistic")
        self.assertEqual(stats.bias_verdict(1.02), "1.02 — gauge was accurate")

    def test_verdict_is_language_free(self) -> None:
        verdict = stats.range_verdict(1.2)
        self.assertEqual(verdict.kind, "optimistic")
        self.assertAlmostEqual(verdict.percent, 20.0)
        self.assertIsNone(stats.range_verdict(None))

    def test_errors_render_in_current_language(self) -> None:
        """Hata anahtarla taşınıyor; metin str() anındaki dilde çıkıyor."""
        error = TripFileError("file.bad_json", line=3)
        self.assertEqual(str(error), "JSON çözümlenemedi (3. satır)")
        i18n.set_language("en")
        self.assertEqual(str(error), "JSON could not be parsed (line 3)")
        record = drive.DriveFile(id="x", ex30id=f"trip-{EPOCH}.json", epoch=EPOCH, kind="ozet", size=999)
        with self.assertRaises(drive.DriveError) as caught:
            drive.check_md5(record, b"12345")
        self.assertEqual(str(caught.exception), f"trip-{EPOCH}.json: size mismatch (Drive 999, downloaded 5 bytes)")
        i18n.set_language("tr")
        self.assertEqual(str(caught.exception), f"trip-{EPOCH}.json: boyut tutmadı (Drive 999, inen 5 bayt)")

    def test_drive_error_text_is_passed_through(self) -> None:
        """Drive'ın kendi iletisi çevrilmiyor; kod ve ileti olduğu gibi."""
        i18n.set_language("en")
        fake = FakeDrive()
        fake.script = [_error(400, "invalid", "Invalid Value")]
        with self.assertRaises(drive.DriveError) as caught:
            _api(fake).list_trips(None)
        self.assertEqual(str(caught.exception), "Drive returned 400: Invalid Value")

    # --- Açılış dili ---------------------------------------------------------

    def test_resolve_precedence(self) -> None:
        self.assertEqual(i18n.resolve(cli="en", saved="tr"), "en")
        self.assertEqual(i18n.resolve(cli=None, saved="en"), "en")
        self.assertEqual(i18n.resolve(cli="xx", saved="tr"), "tr")
        self.assertIn(i18n.resolve(cli=None, saved=None), i18n.LANGUAGES)

    def test_lang_option_is_split_from_paths(self) -> None:
        self.assertEqual(split_language(["--lang", "en", "a.txt"]), ("en", ["a.txt"]))
        self.assertEqual(split_language(["b.txt", "--lang=tr"]), ("tr", ["b.txt"]))
        self.assertEqual(split_language(["c.txt"]), (None, ["c.txt"]))

    def test_settings_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = tmp
            try:
                self.assertEqual(settings.load(), {})
                settings.save(language="en")
                settings.save(other=1)  # ikinci kayıt ilkini ezmemeli
                self.assertEqual(settings.load(), {"language": "en", "other": 1})
                settings.settings_path().write_text("{bozuk", encoding="utf-8")
                self.assertEqual(settings.load(), {})
            finally:
                if old is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = old

    # --- Grafikler -----------------------------------------------------------

    def test_every_chart_draws_in_both_languages(self) -> None:
        """Her grafiği iki dilde ve boş listeyle gerçekten PNG'ye basar.

        Çeviri çağrısı çizim sırasında çalışıyor; yer tutucu hatası ya da ad
        gölgelemesi ancak burada ortaya çıkar.
        """
        trips = read_file(SAMPLE)
        trips.sort(key=lambda t: t.start_epoch)
        for code in i18n.LANGUAGES:
            i18n.set_language(code)
            for key, draw in charts.CHARTS:
                for data, selected in ((trips, len(trips) - 1), ([], None)):
                    with self.subTest(language=code, chart=key, trips=len(data)):
                        fig = Figure(figsize=(8, 6), dpi=60, layout="constrained")
                        draw(fig, data, selected)
                        fig.savefig(io.BytesIO(), format="png")


class ChartAxisTests(unittest.TestCase):
    """Tarih ekseni etiketleri tekil ve okunur olmalı.

    Kusur: matplotlib 4,5 günlük veriye 12 saatte bir tik koyuyor, etiket
    yalnızca günü gösterdiği için her gün iki kez yazılıyordu; aynı gün yapılan
    iki yolculuğun barları da aynı etiketi taşıyordu. Örnek veride 18 eksen
    etkilenmişti.
    """

    def tearDown(self) -> None:
        i18n.set_language("tr")

    @staticmethod
    def _labels(ax) -> list[str]:
        return [label.get_text() for label in ax.get_xticklabels() if label.get_text()]

    def _datasets(self) -> dict[str, list]:
        trips = sorted(read_file(SAMPLE), key=lambda t: t.start_epoch)
        return {
            "5 gün": trips,
            "2 gün": [t for t in trips if t.start_dt.day in (11, 12)],
            "tek gün": [t for t in trips if t.start_dt.day == 12],
        }

    def test_no_axis_repeats_a_label(self) -> None:
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        for code in i18n.LANGUAGES:
            i18n.set_language(code)
            for name, trips in self._datasets().items():
                for key, draw in charts.CHARTS:
                    fig = Figure(figsize=(9.5, 6.4), dpi=100, layout="constrained")
                    FigureCanvasAgg(fig)
                    draw(fig, trips, None)
                    fig.canvas.draw()
                    for i, ax in enumerate(fig.axes):
                        labels = self._labels(ax)
                        with self.subTest(language=code, data=name, chart=key, axis=i):
                            self.assertEqual(len(labels), len(set(labels)), labels)

    def test_labels_keep_the_date_when_days_change(self) -> None:
        """İki günlük veride yalnızca saat yazılırsa "11:23, 09:28" saat geri
        gidiyormuş gibi okunuyordu."""
        trips = self._datasets()["2 gün"]
        labels = charts._unique_labels([t.start_dt for t in trips], charts._time_kind(trips))
        self.assertEqual(labels, ["11.09 10:59", "11.09 11:23", "12.09 09:28", "12.09 09:34"])
        same_day = self._datasets()["tek gün"]
        self.assertEqual(charts._time_kind(same_day), "time")

    def test_zooming_in_switches_to_hours(self) -> None:
        """Tür tiklerden seçildiği için yakınlaştırınca da tutarlı kalıyor."""
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        trips = self._datasets()["5 gün"]
        fig = Figure(figsize=(9.5, 6.4), dpi=100, layout="constrained")
        FigureCanvasAgg(fig)
        charts.draw_consumption(fig, trips, None)
        ax = fig.axes[0]
        fig.canvas.draw()
        self.assertEqual(self._labels(ax)[:2], ["12.09", "13.09"])
        start = trips[-1].start_dt
        ax.set_xlim(start - timedelta(hours=3), start + timedelta(hours=3))
        fig.canvas.draw()
        labels = self._labels(ax)
        self.assertTrue(labels and all(":" in label for label in labels), labels)
        self.assertEqual(len(labels), len(set(labels)))

    def test_tick_kind_follows_tick_spacing(self) -> None:
        day = datetime(2026, 9, 11)
        hours = [day + timedelta(hours=h) for h in (0, 6, 12)]
        halves = [day + timedelta(hours=12 * k) for k in range(4)]
        days = [day + timedelta(days=k) for k in range(4)]
        months = [datetime(2026, m, 1) for m in (6, 7, 8)]
        self.assertEqual(charts._tick_kind(hours), "time")
        self.assertEqual(charts._tick_kind(halves), "daytime")
        self.assertEqual(charts._tick_kind(days), "day")
        self.assertEqual(charts._tick_kind(months), "month")


if __name__ == "__main__":
    unittest.main()
