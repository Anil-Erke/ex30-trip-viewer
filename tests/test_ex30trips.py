"""Çalıştırma: proje kökünde  py -3 -m unittest discover -s tests

Testlerin çapası gerçek veri: `ornek/trips-ornek.txt` araçtan çıkmış bir dışa
aktarım. Beklenen değerler oradaki sayılardan elle hesaplandı.
"""

from __future__ import annotations

import io
import json
import os
import re
import string
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from matplotlib.figure import Figure  # noqa: E402

from ex30trips import app as app_module  # noqa: E402
from ex30trips import charts, drive, i18n, settings, stats  # noqa: E402
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
from ex30trips.model import Trip  # noqa: E402

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
        self.assertAlmostEqual(trip.gps_wheel_ratio, 10.0 / 10.2)
        self.assertEqual(trip.duration_text(), "6 dk 00 sn")

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


class DriveTests(unittest.TestCase):
    """Ağa çıkmayan kısım: yanıt çözümleme ve adres kurma.

    İndirmenin kendisi burada test edilemiyor (gerçek bir uç gerekiyor); bu
    yüzden ağdan GELEN metni işleyen her yol ayrı ayrı sınanıyor — hataların
    çoğu orada.
    """

    @staticmethod
    def _response(content: bytes, *, gz: bool = True, **overrides: object) -> str:
        import base64
        import gzip as gziplib

        blob = gziplib.compress(content) if gz else content
        payload = {
            "ok": True,
            "name": "trips.json",
            "bytes": len(content),
            "gz": gz,
            "data": base64.b64encode(blob).decode("ascii"),
        }
        payload.update(overrides)
        return json.dumps(payload)

    def test_reads_gzipped_payload(self) -> None:
        content = b'[{"startEpoch":1}]'
        self.assertEqual(drive.parse_response(self._response(content)), content)

    def test_reads_plain_payload(self) -> None:
        content = b"merhaba"
        self.assertEqual(drive.parse_response(self._response(content, gz=False)), content)

    def test_rejects_size_mismatch(self) -> None:
        # Yarim inen dosyayi kabul etmek, iyi veriyi bozukla degistirmek olur.
        bad = self._response(b"12345", bytes=999)
        with self.assertRaises(drive.DriveError) as caught:
            drive.parse_response(bad)
        self.assertIn("boyut tutmadı", str(caught.exception))

    def test_server_error_is_reported(self) -> None:
        with self.assertRaises(drive.DriveError) as caught:
            drive.parse_response(json.dumps({"ok": False, "hata": "yetkisiz"}))
        self.assertIn("yetkisiz", str(caught.exception))

    def test_html_response_is_not_silently_accepted(self) -> None:
        # Web uygulamasi yanlis yayinlanmissa Google HTML oturum sayfasi donuyor.
        with self.assertRaises(drive.DriveError):
            drive.parse_response("<html><body>Sign in</body></html>")

    def test_empty_response_is_an_error(self) -> None:
        with self.assertRaises(drive.DriveError):
            drive.parse_response("   ")

    def test_build_url_escapes_and_keeps_existing_query(self) -> None:
        config = drive.Config(url="https://example.com/exec?v=2", secret="a b&c")
        url = drive.build_url(config, "trips.json")
        self.assertIn("?v=2&", url)
        self.assertIn("k=a+b%26c", url)
        self.assertIn("file=trips.json", url)

    def test_config_is_not_ready_when_blank(self) -> None:
        self.assertFalse(drive.Config().ready)
        self.assertFalse(drive.Config(url="  ", secret="x").ready)
        self.assertTrue(drive.Config(url="https://e/exec", secret="x").ready)


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
            r'(?:\bt|i18n\.t|TripFileError|DriveError)\(\s*"([a-z0-9_.\-]+)"'
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
        with self.assertRaises(drive.DriveError) as caught:
            drive.parse_response(DriveTests._response(b"12345", bytes=999))
        self.assertEqual(str(caught.exception), "size mismatch: expected 999, got 5")

    def test_server_error_text_is_passed_through(self) -> None:
        i18n.set_language("en")
        with self.assertRaises(drive.DriveError) as caught:
            drive.parse_response(json.dumps({"ok": False, "hata": "yetkisiz"}))
        self.assertEqual(str(caught.exception), "yetkisiz")

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
