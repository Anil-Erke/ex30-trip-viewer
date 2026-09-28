"""Türkçe metinler — uygulamanın ilk ve referans dili.

Bir anahtar başka dilde eksikse buradaki metin gösterilir; o yüzden bu tablo
her zaman tam olmalı.

Yer tutucular `str.format` sözdizimiyle: `{n}`, `{m:02d}`. Tekil/çoğul ayrımı
gereken dillerde `{n|trip|trips}` biçimi kullanılıyor; Türkçede sayıdan sonra
isim çoğul olmadığı için burada gerek yok.
"""

STRINGS: dict[str, str] = {
    # --- Genel ---------------------------------------------------------------
    "app.title": "EX30 Yolculuk Görüntüleyici",
    "common.cancel": "Vazgeç",
    "common.save": "Kaydet",
    "common.close": "Kapat",

    # --- Birim ve süre ------------------------------------------------------
    # km/s = kilometre/saat. İngilizcede "km/h"; "km/s" orada saniye okunur.
    "unit.speed": "km/s",
    "duration.hm": "{h} sa {m:02d} dk",
    "duration.ms": "{m} dk {s:02d} sn",
    "duration.m": "{m} dk",

    # --- Menü ----------------------------------------------------------------
    "menu.file": "Dosya",
    "menu.add_files": "Dosya ekle…\tCtrl+O",
    "menu.add_folder": "Klasör ekle…",
    "menu.add_sample": "Örnek veriyi ekle",
    "menu.drive_fetch": "Drive'dan al\tCtrl+D",
    "menu.drive_settings": "Drive ayarları…",
    "menu.sources": "Yüklü kaynaklar…",
    "menu.clear": "Kayıtları temizle",
    "menu.reload": "Yenile\tF5",
    "menu.export_csv": "Tabloyu CSV'ye aktar…",
    "menu.export_png": "Grafiği PNG kaydet…",
    "menu.exit": "Çıkış",
    # İki dilde de aynı: yanlış dilde takılan kullanıcı menüyü tanıyabilsin.
    "menu.language": "Dil / Language",
    "menu.help": "Yardım",
    "menu.help_source": "Veri nereden geliyor?",
    "menu.about": "Hakkında",

    # --- Araç çubuğu ---------------------------------------------------------
    "toolbar.add_files": "Dosya ekle",
    "toolbar.add_folder": "Klasör ekle",
    "toolbar.sample": "Örnek veri",
    "toolbar.drive": "Drive'dan al",
    "toolbar.clear": "Temizle",
    "toolbar.period": "Dönem",
    "toolbar.distance": "Mesafe",
    "toolbar.export_csv": "CSV'ye aktar",

    # --- Filtreler -----------------------------------------------------------
    "period.all": "Tüm kayıtlar",
    "period.7": "Son 7 gün",
    "period.30": "Son 30 gün",
    "period.90": "Son 90 gün",
    "period.365": "Son 1 yıl",
    "distance.all": "Hepsi",

    # --- Özet kartları -------------------------------------------------------
    "kpi.trips": "Yolculuk",
    "kpi.km": "Mesafe (km)",
    "kpi.duration": "Süre",
    "kpi.consumption": "Ø tüketim (kWh/100)",
    "kpi.energy": "Net enerji (kWh)",
    "kpi.regen": "Rejen (kWh)",
    "kpi.speed": "Ø hız (km/s)",
    "kpi.bias": "Menzil sapması",

    # --- Yolculuk tablosu ----------------------------------------------------
    "col.start": "Başlangıç",
    "col.duration": "Süre",
    "col.km": "km",
    "col.consumption": "kWh/100",
    "col.energy": "kWh",
    "col.soc": "SoC ↓",
    "col.speed": "Ø km/s",
    "col.temp": "°C",

    # --- Sekmeler ------------------------------------------------------------
    "tab.overview": "Genel bakış",
    "tab.consumption": "Tüketim",
    "tab.energy": "Enerji",
    "tab.battery": "Batarya & menzil",
    "tab.speed": "Hız & rakım",
    "tab.detail": "Yolculuk detayı",

    # --- Yolculuk detayı -----------------------------------------------------
    "detail.none": "Yolculuk seçilmedi",
    "detail.hint": "Soldaki listeden bir yolculuk seç.",
    "detail.col.field": "Ölçüm",
    "detail.col.value": "Değer",
    "detail.sub": "{duration} · {km} km · bitiş {end} · şema {schema} · {source}",
    "detail.no_source": "kaynak yok",
    "detail.group.distance": "— Mesafe ve süre —",
    "detail.group.energy": "— Enerji —",
    "detail.group.battery": "— Batarya ve menzil —",
    "detail.group.speed": "— Hız, sıcaklık, rakım —",
    "detail.group.perf": "— Performans ölçümleri —",
    "detail.gps_km": "GPS mesafesi",
    "detail.wheel_km": "Tekerlek mesafesi",
    "detail.gps_wheel": "GPS ÷ tekerlek",
    "detail.duration": "Süre",
    "detail.net": "Net tüketim",
    "detail.regen": "Rejen",
    "detail.gross": "Brüt tüketim",
    "detail.regen_share": "Rejen payı",
    "detail.consumption": "Tüketim",
    "detail.potential": "Tırmanışın potansiyel enerjisi",
    "detail.soc": "SoC başlangıç → bitiş",
    "detail.soc_drop": "SoC düşüşü",
    "detail.range": "Menzil başlangıç → bitiş",
    "detail.range_drop": "Menzil düşüşü",
    "detail.bias": "Gösterge sapması",
    "detail.avg_speed": "Ortalama hız",
    "detail.max_speed": "Azami hız",
    "detail.temp": "Sıcaklık başlangıç / ortalama",
    "detail.alt_gain": "Rakım kazancı",
    "detail.alt_loss": "Rakım kaybı",
    "detail.alt_net": "Net rakım",

    # --- A4 performans ölçümleri (PerfKind) ----------------------------------
    "perf.0-100": "0–100 km/s",
    "perf.0-60": "0–60 km/s",
    "perf.80-120": "80–120 km/s",
    "perf.100-0": "100–0 km/s fren",

    # --- Menzil göstergesi kararı (RangeAuditor.Verdict) ---------------------
    "bias.accurate": "{factor} — gösterge tuttu",
    "bias.optimistic": "{factor} — {percent} iyimser",
    "bias.pessimistic": "{factor} — {percent} kötümser",

    # --- Durum çubuğu --------------------------------------------------------
    "status.empty": "Araçtan dışa aktardığın trips-*.txt dosyasını ekle (Ctrl+O) ya da 'Örnek veri'ye bas. Kaynaklar birikir.",
    "status.no_match": "Filtreye uyan yolculuk yok — dönem ya da mesafe filtresini gevşet.",
    "status.showing": "{first} – {last} arası {n} yolculuk gösteriliyor",
    "status.added": "{label}: {fresh} yeni yolculuk eklendi · {sources} kaynakta toplam {total}",
    "status.removed": "'{label}' kaldırıldı · {n} yolculuk kaldı",
    "status.reloaded": "{n} kaynak yeniden okundu.",
    "status.drive_downloading": "Drive'dan indiriliyor…",
    "status.drive_failed": "Drive'dan indirilemedi.",
    "status.csv_saved": "CSV kaydedildi: {path}",
    "status.png_saved": "Grafik kaydedildi: {path}",
    "files.sources": "{n} kaynak",
    "files.files": "{n} dosya",
    "files.trips": "{n} yolculuk",
    "files.duplicates": "{n} yinelenen kayıt teklendi",
    "files.failures": "{n} dosya okunamadı",

    # --- Kaynaklar -----------------------------------------------------------
    "source.kind.file": "dosya",
    "source.kind.folder": "klasör",
    "source.kind.sample": "örnek",
    "source.kind.drive": "drive",
    "source.kind.cli": "komut satırı",
    "sources.title": "Yüklü kaynaklar",
    "sources.intro": "Ekrandaki liste bu kaynakların birleşimi; aynı yolculuk birden çoğunda varsa bir kez sayılır.",
    "sources.col.kind": "Tür",
    "sources.col.label": "Kaynak",
    "sources.col.files": "Dosya",
    "sources.col.trips": "Yolculuk",
    "sources.remove": "Seçileni kaldır",
    "sources.clear_all": "Hepsini temizle",
    "sources.none": "Henüz kaynak yok. 'Dosya ekle', 'Klasör ekle' ya da 'Drive'dan al' ile ekleyebilirsin; eklenenler birikir.",

    # --- Dosya seçme ve yükleme ----------------------------------------------
    "dialog.pick_files": "Yolculuk dosyası seç",
    "dialog.pick_folder": "İçinde trips-*.txt olan klasörü seç",
    "filetype.trips": "Yolculuk kaydı",
    "filetype.text": "Metin / JSON",
    "filetype.all": "Tüm dosyalar",
    "load.failed": "Yolculuk kaydı okunamadı.",
    "load.nothing_found": "Seçilen yerde trips-*.txt yok.",
    "load.kept": "Ekrandaki kayıtlar olduğu gibi duruyor.",
    "load.sample_missing": "Örnek dosya bulunamadı:\n{path}",
    "file.empty": "dosya boş",
    "file.bad_json": "JSON çözümlenemedi ({line}. satır)",
    "file.no_trips": "içinde yolculuk kaydı yok",
    "file.unreadable": "kayıtların hiçbiri okunamadı",

    # --- Drive ---------------------------------------------------------------
    "drive.settings.title": "Drive ayarları",
    "drive.settings.intro": "Araçtaki uygulamanın yüklediği kayıtları indirmek için\nApps Script web uygulamasının adresi ve OKUMA anahtarı.",
    "drive.settings.url": "Adres (/exec)",
    "drive.settings.secret": "Okuma anahtarı",
    "drive.settings.path": "Ayarlar: {path}",
    "drive.settings.both_required": "Adres ve anahtarın ikisi de gerekli.",
    "drive.settings.save_failed": "Ayarlar kaydedilemedi:\n{error}",
    "drive.failed": "Drive'dan indirilemedi:\n\n{error}",
    "drive.err.unexpected": "beklenmeyen hata: {error}",
    "drive.err.empty": "sunucu boş yanıt verdi",
    "drive.err.not_json": "yanıt JSON değil — adres yanlış olabilir ya da web uygulaması 'Erişimi olan: Herkes' olarak yayınlanmamış",
    "drive.err.bad_shape": "yanıt beklenen biçimde değil",
    # Sunucunun kendi hata metni olduğu gibi aktarılıyor.
    "drive.err.server": "{message}",
    "drive.err.unknown_server": "bilinmeyen sunucu hatası",
    "drive.err.no_data": "yanıtta dosya içeriği yok",
    "drive.err.base64": "base64 çözülemedi: {error}",
    "drive.err.gzip": "gzip açılamadı: {error}",
    "drive.err.size": "boyut tutmadı: beklenen {expected}, gelen {got}",
    "drive.err.not_configured": "Drive adresi ve anahtarı tanımlı değil",
    "drive.err.http": "sunucu {code} döndü",
    "drive.err.connect": "bağlantı kurulamadı: {reason}",
    "drive.err.save": "indirilen dosya kaydedilemedi: {error}",

    # --- Dışa aktarma --------------------------------------------------------
    "export.nothing": "Aktarılacak yolculuk yok.",
    "export.csv_title": "CSV olarak kaydet",
    "export.csv_filename": "ex30-yolculuklar.csv",
    "export.csv_failed": "CSV yazılamadı:\n{error}",
    "export.pick_chart": "Önce bir grafik sekmesi seç.",
    "export.png_title": "Grafiği kaydet",
    "csv.start": "Başlangıç",
    "csv.end": "Bitiş",
    "csv.duration": "Süre (sn)",
    "csv.gps_km": "GPS mesafe (km)",
    "csv.wheel_km": "Tekerlek mesafe (km)",
    "csv.net": "Net enerji (kWh)",
    "csv.regen": "Rejen (kWh)",
    "csv.consumption": "Tüketim (kWh/100km)",
    "csv.soc_start": "SoC başlangıç (%)",
    "csv.soc_end": "SoC bitiş (%)",
    "csv.range_start": "Menzil başlangıç (km)",
    "csv.range_end": "Menzil bitiş (km)",
    "csv.bias": "Menzil sapması",
    "csv.avg_speed": "Ortalama hız (km/s)",
    "csv.max_speed": "Azami hız (km/s)",
    "csv.temp": "Sıcaklık ortalama (°C)",
    "csv.alt_gain": "Rakım kazancı (m)",
    "csv.alt_loss": "Rakım kaybı (m)",
    "csv.potential": "Potansiyel enerji (kWh)",
    "csv.schema": "Şema",
    "csv.source": "Kaynak",

    # --- Grafikler -----------------------------------------------------------
    "chart.failed": "Grafik çizilemedi:\n{error}",
    "chart.no_trips": "Gösterilecek yolculuk yok.",
    "chart.average": "ortalama {value}",
    "chart.day.ylabel": "günlük mesafe (km)",
    "chart.day.title": "Günlük mesafe ve kümülatif toplam",
    "chart.day.cumulative": "kümülatif (km)",
    "chart.band.title": "Dış sıcaklığa göre tüketim",
    "chart.band.none": "Enerji ölçülen yolculuk yok:\ntüketim bandı hesaplanamıyor.",
    "chart.hist.xlabel": "yolculuk uzunluğu (km)",
    "chart.hist.ylabel": "yolculuk sayısı",
    "chart.hist.title": "Yolculuk uzunluğu dağılımı",
    "chart.hist.median": "medyan {value} km",
    "chart.hist.none": "Mesafesi olan yolculuk yok.",
    "chart.cons.none": "Hiçbir yolculukta enerji ölçülememiş.\nTüketim, güç integralinden hesaplanıyor; araç güç property'sini vermediyse kayıtta bu alan boş kalır.",
    "chart.cons.weighted": "enerji ağırlıklı ortalama {value}",
    "chart.cons.title": "Yolculuk başına tüketim (nokta büyüklüğü = mesafe)",
    "chart.cons.speed.xlabel": "ortalama hız (km/s)",
    "chart.cons.speed.title": "Tüketim ↔ ortalama hız",
    "chart.cons.temp.xlabel": "dış sıcaklık (°C)",
    "chart.cons.temp.title": "Tüketim ↔ dış sıcaklık",
    "chart.no_speed": "Hız verisi yok.",
    "chart.no_temp": "Sıcaklık verisi yok.",
    "chart.energy.none": "Enerji ölçülen yolculuk yok.",
    "chart.energy.net": "net tüketim",
    "chart.energy.regen": "rejenle geri kazanılan",
    "chart.energy.title": "Yolculuk başına enerji — net + rejen = brüt",
    "chart.share.ylabel": "brütün yüzdesi",
    "chart.share.title": "Rejen payı",
    "chart.share.none": "Rejen verisi yok.",
    "chart.descent.xlabel": "toplam iniş (m)",
    "chart.descent.ylabel": "rejen (kWh)",
    "chart.descent.title": "Rejen ↔ iniş",
    "chart.descent.none": "Rakım ya da rejen verisi yok.",
    "chart.battery.none": "Batarya ya da menzil verisi olan yolculuk yok.",
    "chart.soc.start": "başlangıç SoC",
    "chart.soc.end": "bitiş SoC",
    "chart.soc.title": "Yolculuk boyunca şarj durumu — iki nokta arası yolculukta harcanan",
    "chart.soc.none": "SoC verisi yok.",
    "chart.bias.ylabel": "menzil düşüşü ÷ km",
    "chart.bias.title": "Gösterge menzili ne kadar doğru",
    "chart.bias.note": "1,0 üstü: iyimser · altı: kötümser",
    "chart.bias.none": "{km} km üstü ve menzil düşüşü\nölçülen yolculuk yok.",
    "chart.range.xlabel": "gidilen mesafe (km)",
    "chart.range.ylabel": "menzil düşüşü (km)",
    "chart.range.title": "Menzil düşüşü ↔ mesafe (kesikli çizgi: birebir)",
    "chart.range.none": "Menzil verisi yok.",
    "chart.speed.average": "ortalama",
    "chart.speed.top": "azami",
    "chart.speed.title": "Ortalama ve azami hız",
    "chart.alt.climb": "tırmanış",
    "chart.alt.descent": "iniş",
    "chart.alt.ylabel": "metre",
    "chart.alt.title": "Rakım kazancı ve kaybı",
    "chart.alt.none": "Rakım verisi yok.",
    "chart.ratio.ylabel": "GPS ÷ tekerlek",
    "chart.ratio.title": "GPS mesafesi ↔ tekerlek mesafesi",
    "chart.ratio.none": "Tekerlek mesafesi yok:\nkayıtlar şema 3 öncesi.",

    # --- Yardım --------------------------------------------------------------
    "help.source": (
        "Kayıtlar araçtaki EX30 Telemetry / EX30 Yol Analizi uygulamasının "
        "tuttuğu trips.json dosyasından geliyor.\n\n"
        "Araçta: Ayarlar → Veriyi dışa aktar. Dosya trips-YYYYAAGG-SSDD.txt "
        "adıyla çıkıyor; Bluetooth ya da Wi-Fi ile bilgisayara aldıktan sonra "
        "burada 'Dosya ekle' ile açılıyor.\n\n"
        "Kaynaklar birikir: Drive'dan son kayıtları aldıktan sonra eski "
        "dışa aktarımların durduğu klasörü de eklersen ikisi birlikte "
        "gösterilir. Aynı yolculuk iki kaynakta da varsa alanı daha dolu "
        "olan kopya tutulur, bir kez sayılır.\n\n"
        "'Temizle' hepsini bırakır; 'Yüklü kaynaklar…' tek tek kaldırmaya "
        "yarar."
    ),
    "help.about": (
        "{title}\n\n"
        "Volvo EX30'dan dışa aktarılan yolculuk kayıtlarını masaüstünde "
        "grafikle gösterir.\n\n"
        "Ortalamalar araçtaki TripStats ile aynı tanımları kullanır: "
        "tüketim enerji ağırlıklı, menzil sapması mesafe ağırlıklı.\n\n"
        "Python {python} · matplotlib {mpl}"
    ),

    # --- Başlangıç -----------------------------------------------------------
    "startup.missing": "{name} kurulu değil.\n\nKurmak için:\n    py -m pip install matplotlib\n\nAyrıntı: {detail}",
}
