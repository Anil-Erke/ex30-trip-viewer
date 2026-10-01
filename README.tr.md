# EX30 Trip Viewer (EX30 Yolculuk Görüntüleyici)

[English](README.md) · **Türkçe**

Volvo EX30'dan gelen yolculuk kayıtlarını Windows'ta grafikle gösteren
masaüstü uygulaması. Python + Tkinter + matplotlib; kurulum gerektirmez,
klasörden doğrudan çalışır.

> **Resmî olmayan proje.** Volvo Cars ile bağlantısı yoktur, Volvo tarafından
> onaylanmamış veya desteklenmemektedir. "Volvo" ve "EX30" sahiplerinin ticari
> markalarıdır; burada yalnızca uyumluluğu belirtmek için kullanılır. Yazılım
> **"olduğu gibi", hiçbir garanti olmaksızın** sunulur; gösterilen değerler
> tahminidir.

![Genel bakış](screenshots/tr-overview.png)

<p>
  <img src="screenshots/tr-consumption.png" width="420" alt="Tüketim sekmesi">
  <img src="screenshots/tr-battery-range.png" width="420" alt="Batarya ve menzil sekmesi">
</p>

<sub>Ekran görüntüleri depodaki örnek veriyle (`ornek/trips-ornek.txt`) alındı.</sub>

Veri iki yoldan gelir:

- **Google Drive (önerilen):** araçtaki [EX30 Telemetry](https://github.com/Anil-Erke/ex30-telemetry) her yolculuğu
  kendi Drive'ınıza yükler; burada aynı Google hesabıyla girip **Drive'dan al**
  dersiniz. GPS izi de gelir (Rota sekmesi). Ayrıntı: [Drive'dan alma](#drivedan-alma).
- **Dosya:** EX30 Telemetry'nin *Dışa aktar* düğmesi `trips.json`'u araçta
  `trips-YYYYAAGG-SSDD.txt` adıyla yazar (`calib/DataExporter.kt`); dosyayı
  bilgisayara taşıyıp *Dosya ekle* ile açarsınız.

## Derlemeden önce doldurmanız gerekenler

Dosyadan okuma ve örnek veri için **hiçbir şey**. Yalnızca **Google Drive**
için kendi Google Cloud OAuth istemciniz gerekir:

| Ne | Nerede | Zorunlu mu? |
|---|---|---|
| *Desktop app* türünde OAuth istemcisi | `oauth.properties` içinde `desktopClientId` ve `desktopClientSecret` | Drive için evet; exe üretmek için de (`exe-olustur.ps1` istemciyi gömer) |

İstemciyi, araçtaki uygulamanın istemcisiyle **aynı Google Cloud projesinde**
açın; başka projedeki bir istemci aracın yüklediği dosyaları göremez. Adım adım
kurulum: EX30 Telemetry README'si,
[Google Drive eşitleme](https://github.com/Anil-Erke/ex30-telemetry/blob/main/README.tr.md#google-drive-eşitleme-isteğe-bağlı).
Şablon olarak oradaki `oauth.properties.example` dosyasını kullanabilirsiniz.

`oauth.properties` dosyasını bu projenin köküne koyun ya da yolunu
`EX30_OAUTH_PROPERTIES` ortam değişkeniyle verin. `oauth.properties` ve ondan
üretilen `ex30trips/_oauth.py` `.gitignore` içindedir: **asla depoya eklemeyin.**

## Çalıştırma

```
calistir.bat
```

ya da komut satırından:

```
py -3 -m ex30trips
py -3 -m ex30trips "C:\yol\trips-20260915-0909.txt"
py -3 -m ex30trips "C:\indirilenler"
py -3 -m ex30trips --lang en
```

Dosya ya da klasör yolu verilirse açılışta yüklenir.

## Dil / Language

Arayüz **Türkçe** ve **İngilizce**. Menüde **Dil / Language** → *Türkçe* ya da
*English*; seçim anında uygulanır ve kalıcıdır. Başlık iki dilli, dil adları
kendi dillerinde yazılı — yanlış dilde açılan uygulamada da geri dönüş yolu
bulunuyor.

Dil değişince pencere kapanıp açılmıyor: widget'lar yeni dille yeniden
kuruluyor, **yüklü kaynaklar, filtreler, sıralama, seçili yolculuk ve açık
sekme yerinde kalıyor**; hiçbir dosya yeniden okunmuyor.

Açılış dilinin önceliği:

1. `--lang tr|en` — yalnızca o açılış için, kayıtlı seçimi değiştirmez
2. Dil menüsünde yapılan son seçim — `%LOCALAPPDATA%\EX30TripViewer\settings.json`
3. Windows **arayüz** dili (bölge biçimi değil): Türkçeyse Türkçe, değilse İngilizce

Dile bağlı olan yalnızca metin değil:

| | Türkçe | English |
|---|---|---|
| Sayı | 1.234,5 | 1,234.5 |
| Yüzde | %33 | 33% |
| Tarih | 15.09.2026 08:02 | 15 Sep 2026 08:02 |
| Hız | km/s (kilometre/**saat**) | km/h |
| Süre | 1 sa 07 dk | 1 h 07 min |
| CSV | `;` ayraç, ondalık virgül | `,` ayraç, ondalık nokta, ISO tarih |

Ay adları işletim sisteminin yerel ayarından alınmıyor (`strftime("%b")` Türkçe
Windows'ta İngilizce arayüze "Eyl" yazardı); `i18n.py` kendisi kuruyor.

Metinler `ex30trips/lang/tr.py` ve `lang/en.py` tablolarında — araç
uygulamasındaki `values/` + `values-tr/` düzeninin karşılığı. Kod yalnızca
anahtar kullanıyor (`t("menu.file")`). İki tablonun anahtarları ve yer
tutucuları testle eşit tutuluyor; koddaki her anahtarın tabloda olduğu da
denetleniyor. Yeni metin eklerken iki tabloya birden yaz, yoksa test düşer.

İngilizcede tekil/çoğul `{n|trip|trips}` biçimiyle: "1 trip", "5 trips".
Türkçede sayıdan sonra isim çoğul olmadığı için gerekmiyor.

**Tuzak:** bu kod tabanında `t` yolculuk değişkeninin adı. `charts.py`,
`stats.py` ve `model.py` fonksiyonların içinde `t = ...` atıyor; oralarda
çeviri çağrısı `t(...)` yazılırsa Python o fonksiyondaki bütün `t`'leri yerel
sayıp `UnboundLocalError` verir. Bu modüllerde her zaman `i18n.t(...)`.
`app.py`'de `t` çeviri fonksiyonu, yolculuk değişkeni `trip`.

## Kaynaklar birikir

**Dosya ekle**, **Klasör ekle**, **Örnek veri** ve **Drive'dan al** yüklü
kayıtların yerine geçmez, üstüne ekler. Drive'da yalnızca son günler duruyorsa
eski dışa aktarımların olduğu klasörü de ekleyip ikisini tek listede
görebilirsin; grafikler, özet kartları ve CSV hep birleşik kümeyi kullanır.

Aynı yolculuk birden çok kaynakta varsa `startEpoch` ile tekleniyor, bir kez
sayılıyor. Aynı yol ikinci kez seçilirse kaynak çoğalmıyor, tazesiyle
değişiyor — Drive'dan tekrar almak da yüklü Drive kaynağını yeniliyor.

| İşlem | Nerede |
| --- | --- |
| Hepsini bırak | **Temizle** düğmesi · *Dosya → Kayıtları temizle* |
| Tek kaynağı çıkar | *Dosya → Yüklü kaynaklar…* (durum çubuğundaki özete tıklamak da açar) |
| Hepsini diskten yeniden oku | **F5** |

Durum çubuğunun sağı kaç kaynak, kaç dosya, kaç yolculuk yüklü olduğunu ve
kaç yinelenen kaydın elendiğini yazıyor.

## Drive'dan alma

Araçtaki **EX30 Telemetry** her yolculuğu bitince, sürücünün araçta bağladığı
**Google hesabının kendi Drive'ına** yüklüyor: yolculuğun **özeti** ve **1 Hz
GPS izi** ayrı dosyalar. Arada sunucu yok; her kullanıcı kendi hesabıyla
bağlanıyor, veriler birbirine karışmıyor. Buradaki **"Drive'dan al"** düğmesi
(Ctrl+D) aynı hesabın Drive'ındaki yeni özetleri indirip yüklü kaynaklara
ekliyor — dosya taşımak, USB, telefon yok.

Protokolün tek kaynağı EX30 Telemetry deposundaki
[`drive-sync/PROTOKOL.md`](https://github.com/Anil-Erke/ex30-telemetry/blob/main/drive-sync/PROTOKOL.md) (**sürüm 3**). Buradaki karşılığı `ex30trips/drive.py`
(Drive REST) ve `ex30trips/auth.py` (Google girişi); protokol değişecekse önce o
dosya değişir, araç, telefon ve bu uygulama birlikte etkileniyor.

### Google hesabı

*Dosya → Google hesabı…* bağlı e-postayı gösteriyor, **Giriş** ve **Çıkış**
buradan. Hesap bağlı değilken "Drive'dan al" önce bu pencereyi açıyor, giriş
yapılınca indirmeye kendiliğinden devam ediyor.

- Giriş tarayıcıda: "Desktop app" türündeki OAuth istemcisiyle **loopback +
  PKCE** (`http://127.0.0.1:<rastgele port>`). Her girişte hesap seçimi
  soruluyor — aynı bilgisayarda başka biri kendi hesabıyla girebilsin.
- İzin **yalnızca `drive.file`** (+ hangi hesap olduğunu göstermek için
  `openid email`). Uygulama Drive'da yalnızca aynı Cloud projesindeki EX30
  istemcilerinin oluşturduğu dosyaları görüyor, kişinin geri kalan Drive'ına
  erişimi yok. **Drive'a hiçbir şey yazmıyor.**
- **İzin kutusu tuzağı:** Google'ın onay ekranında Drive kutusu boş
  bırakılabiliyor; giriş başarılı görünür ama her Drive çağrısı 403 döner.
  Token yanıtındaki `scope`'ta `drive.file` yoksa giriş reddediliyor ve "onay
  ekranında Drive kutusunu işaretle" deniyor. Aynı denetim her token
  yenilemesinde de var.
- Refresh token `%LOCALAPPDATA%\EX30TripViewer\hesap.json` içinde, **DPAPI**
  ile şifreli (`ctypes` + `CryptProtectData`; Windows oturumuna bağlı, dosyayı
  başka kullanıcıya ya da bilgisayara kopyalamak işe yaramıyor). Access token
  yalnızca bellekte.
- Google `invalid_grant` derse (erişim geri alındı, token öldü) token siliniyor
  ve yeniden giriş isteniyor.
- **Çıkış** token'ı siliyor (Google'da da iptal ediyor), o hesabın önbelleğini
  ve imlecini siliyor, o önbellekten yüklenmiş Drive kaynağını ekrandan
  kaldırıyor. Drive'daki dosyalara dokunulmuyor; yeniden girince hepsi iner.

### Artımlı eşitleme (PROTOKOL.md §4)

- Drive REST v3 `files.list`:
  `appProperties has { key='ex30' and value='trip' } and trashed=false and createdTime > '<imleç − 5 dk>'`,
  `orderBy=createdTime`, `pageSize=1000`, `nextPageToken` bitene kadar sayfalı.
  Dosyalar yol ya da adla değil **`appProperties`** ile bulunuyor; kullanıcı bir
  dosyayı taşısa ya da adını değiştirse de eşleşme bozulmuyor.
- **İmleç** görülen en büyük `createdTime` (RFC 3339) — yolculuk zamanı değil
  Drive'a **eklenme** zamanı: araç ağ yokken biriktirdiği eski bir yolculuğu
  günler sonra yüklese de gelir. Bir sonraki istekte **5 dakika geri** çekilerek
  kullanılıyor (Drive listesi yeni dosyayı gecikmeyle gösterebiliyor); örtüşme
  yüzünden iki listede birden gelen dosya `ex30id` ile tekleniyor.
- Yerelde olmayan her özet `files/<id>?alt=media` ile **ham bayt** olarak
  iniyor (dört paralel istek) ve **`md5Checksum` ile doğrulanıyor**; tutmazsa
  diske hiçbir şey yazılmıyor, eldeki dosyaya dokunulmuyor. Durum çubuğunda
  "Drive: 12/300 özet indiriliyor…".
- **İmleç ancak listedeki her şey indiyse ilerliyor.** Bir özet inmezse inenler
  diskte kalıyor, imleç yerinde; bir sonraki "Drive'dan al" aynı listeyi alıp
  yalnızca kalanları deniyor.
- **Boşluk denetimi:** Drive'da sürüm 2'deki `toplam` yok. Yerine ilk
  eşitlemede, **günde en az bir kez** ve *Dosya → Drive'ı baştan tara* ile
  **imleçsiz tam liste** alınıyor; yerelde olmayan her şey iniyor. Tam liste
  yalnızca metadata (1000 dosya başına tek istek). Durum çubuğu son tam taramanın
  zamanını yazıyor.
- Hata ölçütü **HTTP durum kodu**: 401 → token yenilenip bir kez tekrar
  deneniyor, yenisi de reddedilirse yeniden giriş · 403 `insufficientPermissions`
  → Drive izni yok, yeniden giriş · 429 / 403 `rateLimitExceeded` / 5xx → 1, 2,
  4 sn geri çekilip tekrar · 404 → dosya Drive'da yok. Drive'ın kendi hata
  iletisi olduğu gibi gösteriliyor.
- İzler eşitlemede **inmiyor**, yalnızca Drive kimlikleri kaydediliyor;
  yolculuk açılınca iniyor (bkz. Rota sekmesi).

### Sürüm 2'den geçiş

İlk açılışta eski Apps Script ayarı (`drive.json`: adres + okuma anahtarı),
imleç (`esitleme.json`) ve sürüm 2 önbelleği (`yolculuklar\`, `indirilen\`)
varsa **bir kez** siliniyor ve kısa bir not gösteriliyor. İçlerinde sürüm 3'te
yeniden inmeyecek bir şey yok (PROTOKOL.md §4.1): araç hesap bağlanınca
içindeki bütün yolculukları Drive'a gönderiyor. Dil ayarı (`settings.json`)
kalıyor. Apps Script'in oluşturduğu dosyalar zaten görünmüyor — `drive.file`
kuralı gereği iki dünya ayrı.

### Önbellek

Hesap başına ayrı, `%LOCALAPPDATA%\EX30TripViewer\` altında:

| Yol | Ne |
|---|---|
| `hesap.json` | bağlı hesabın e-postası + DPAPI ile şifreli refresh token |
| `hesaplar\<e-posta>\esitleme.json` | imleç (`createdTime`), son tam tarama zamanı, izi olan yolculukların Drive kimlikleri |
| `hesaplar\<e-posta>\yolculuklar\<yyyy>\<MM>\trip-<e>.json` | özetler — Drive'daki `EX30 Trips/yolculuklar/` ile aynı yıl/ay düzeni (İstanbul saati) |
| `hesaplar\<e-posta>\yolculuklar\<yyyy>\<MM>\trip-<e>.csv.gz` | GPS izleri, Drive'daki gzip'li hâliyle baytı baytına |
| `settings.json` | arayüz dili |

Dosyalar Drive'da asla değişmediği için bir kez inen tekrar inmiyor; yazma
önce `.part` dosyasına, sonra yerine yapılıyor ki yarım kalan dosya "inmiş"
sayılmasın. **Drive kaynağı hesabın `yolculuklar\` klasörünün tamamı**: 300
yolculuk sınırı olmadan birikmiş bütün geçmiş, ağ yokken de F5 ile açılıyor.
Özet tek bir JSON nesnesi (dizi değil); `loader` onu tek yolculuk olarak
okuyor, `startEpoch` teklemesi ve "zengin kopya kazanır" kuralı aynen geçerli.

### OAuth istemcisi

Masaüstü istemcisinin kimliği ve sırrı **depoya girmiyor**. Kaynak
`oauth.properties` (`desktopClientId`, `desktopClientSecret`).
Derleme sırasında `araclar\oauth-gom.py` bunları `ex30trips\_oauth.py`'ye
yazıyor (`.gitignore`'da) ve exe'ye o giriyor. Kaynaktan çalışırken
`_oauth.py` yoksa `oauth.properties` doğrudan okunuyor (`EX30_OAUTH_PROPERTIES`
ortam değişkeni, proje kökü ya da yan klasör olarak tam bu adla duran
`EX30 Telemetry\`; GitHub'dan klonlanan `ex30-telemetry` klasörüne bakılmaz). Google
masaüstü uygulamalarında bu değerleri gizli saymıyor — tek başlarına hiçbir
veriye erişim vermiyorlar; kişisel erişim her kullanıcının kendi token'ında.

Cloud Console'da izin ekranı **"In production"** durumunda olmalı: "Testing"
durumunda refresh token 7 günde ölüyor (`drive.file` hassas izin değil, Google
incelemesi gerekmiyor).

## Bağımlılık

Gereken tek bağımlılık
matplotlib (numpy'yi kendisi getiriyor). Rota haritası, Google girişi ve Drive
REST için de yeni bağımlılık eklenmedi — hepsi standart kütüphane (`urllib`,
`http.server`, DPAPI için `ctypes`):

```
py -3 -m pip install -r requirements.txt
```

Tkinter, Windows'taki Python kurulumunda hazır gelir.

## Exe üretme

```
.\exe-olustur.ps1
```

Betik sırasıyla Python'u bulur, eksik bağımlılıkları kurar, birim testlerini
çalıştırır, ikonu üretir, Google OAuth istemcisini gömer
(`araclar\oauth-gom.py` → `ex30trips\_oauth.py`; `oauth.properties`
bulunamazsa derleme durur) ve PyInstaller ile paketler. Testler geçmezse derleme
yapılmaz — bozuk kod exe'ye girmesin. Çift tıklamayla çalıştırmak için
`exe-olustur.bat` var (PowerShell politika engeline takılmadan çağırıyor).

| Anahtar | Ne yapar |
|---|---|
| *(yok)* | Tek dosya: `dist\EX30 Yolculuk Görüntüleyici.exe` (~39 MB) |
| `-Klasor` | Klasör kipi: `dist\EX30 Yolculuk Görüntüleyici\…` — exe 8,4 MB, anında açılır |
| `-TestleriAtla` | Testleri çalıştırmadan derler |
| `-Temizle` | `build/`, `dist/` ve `*.spec` siler, derleme yapmaz |
| `-Calistir` | Derleme bitince exe'yi açar |

Tek dosya kipinde exe kendini her açılışta geçici klasöre açıyor; ilk pencere
bu makinede **2,5 saniyede** geldi. Sık açacaksan `-Klasor` daha rahat.

Örnek veri exe'nin içine gömülüyor; paketlenmiş hâlde kaynak yolu
`sys._MEIPASS`'ten çözülüyor (`app.resource_path`), o yüzden "Örnek veri"
düğmesi exe'de de çalışıyor. İkon `assets/ex30.ico` — yoksa `araclar/ikon-uret.py`
Pillow ile üretiyor, palet arayüzle aynı.

Not: PowerShell betiği UTF-8 **BOM ile** kaydedildi. Windows PowerShell 5.1
BOM'suz dosyayı sistem kod sayfasıyla okuyup Türkçe karakterleri bozuyor
(Windows'taki kod sayfası sorununun PowerShell akrabası). Betiği düzenlerken BOM'u
koru.

## Ekranda ne var

**Sol sütun** — filtrelenmiş kümenin özeti (yolculuk sayısı, mesafe, süre,
ortalama tüketim, net enerji, rejen, ortalama hız, menzil sapması) ve yolculuk
tablosu. Sütun başlığına tıklayınca sıralama değişir, satıra çift tıklayınca
detay sekmesi açılır.

**Sağ sekmeler**

| Sekme | Ne gösteriyor |
|---|---|
| Genel bakış | Günlük mesafe + kümülatif toplam, dış sıcaklık bandına göre tüketim, yolculuk uzunluğu dağılımı |
| Tüketim | Yolculuk başına kWh/100 km, tüketim ↔ ortalama hız, tüketim ↔ dış sıcaklık |
| Enerji | Net + rejen = brüt yığılmış bar, rejen payı, rejen ↔ iniş |
| Batarya & menzil | Yolculuk başına SoC başlangıç→bitiş, gösterge menzil sapması, menzil düşüşü ↔ gerçek mesafe |
| Hız & rakım | Ortalama–azami hız, rakım kazancı/kaybı, GPS ↔ tekerlek mesafesi |
| Yolculuk detayı | Seçili yolculuğun bütün alanları, A4 performans ölçümleri ve GPS izinin durumu |
| Rota | Seçili yolculuğun GPS izi: rota çizimi, irtifa profili, hız ve güç |

Seçili yolculuk bütün grafiklerde vurgulanıyor.

### Rota sekmesi

İz, yolculuk detayı ya da Rota sekmesi açıkken iniyor (listede gezinirken her
satır için Drive'a gidilmiyor) ve hesabın önbelleğinde kalıyor. Bu hesapla
eşitlendiyse izi olan yolculuklar zaten biliniyor (listede `tur=iz` kaydı olmayan
yolculuğun izi yok), izi olmayan yolculukta ağa çıkmadan "iz yok" yazıyor
(0.7.2 öncesi yolculuklar, GPS'siz sürüş). Hiç eşitlenmemişse iz `ex30id` ile
Drive'da aranıyor. Google hesabı bağlı değilse iz de yok.

- **Rota** — enlem/boylam; çizginin rengi hıza, güce ya da irtifaya göre
  seçiliyor. Güçte skala iki yönlü: sıfır ortada, rejen (negatif) yeşil,
  tüketim turuncu→kırmızı. Harita karosu yok, yalnızca matplotlib — en-boy
  oranı enleme göre düzeltiliyor (İstanbul'da boylamın bir derecesi enlemin
  ~%75'i; düzeltilmezse doğu-batı yolları uzun görünür).
- **İrtifa profili** — ham GPS irtifası + 15 noktalık kayan ortalama (eksik
  noktayı atlıyor, sıfır saymıyor).
- **Hız** (gösterge + GPS) ve **güç** — rejen bölgeleri yeşil.

Üç profilin x ekseni aynı mesafe (`dist_m`, km) ve **bağlı**: birini
yakınlaştırınca üçü birlikte gidiyor, haritada da o aralık vurgulanıyor.

İz biçimi (PROTOKOL.md §3.2) `ex30trips/track.py`'de okunuyor: ilk satırdaki
biçim sürümü bilinmiyorsa iz okunmuyor ve bu söyleniyor; sütunlar **adla**
okunuyor (araç sütun ekleyebilir, sırayı değiştirebilir); boş alan None.

**Dosya → İzi CSV'ye aktar…** (ya da Rota sekmesindeki düğme) seçili izi
tablo CSV'siyle aynı kurallarla yazıyor. Grafiklerin altındaki araç
çubuğuyla yakınlaştırma/kaydırma yapılabiliyor; **Dosya → Grafiği PNG kaydet**
görünen sekmeyi dosyaya basıyor.

## Veriyle ilgili kararlar

Sayılar araçtaki hesapla aynı kalsın diye tanımlar `trip/TripStats.kt` ve
`trip/RangeAuditor.kt`'tan birebir alındı:

- **Ortalama tüketim enerji ağırlıklı.** Yolculuk başına kWh/100 km değerlerinin
  düz ortalaması 2 km'lik bir yolculuğu 200 km'likle aynı ağırlıkta sayardı.
- **Menzil sapması mesafe ağırlıklı** ve yalnızca ≥ 5 km yolculuklarda var:
  `RANGE_REMAINING` gerçek araçta 1 km adımlarla değişiyor, 2 km'lik bir
  yolculukta tek adım oranı %50 saptırıyor.
- **`energyKwh` NET tüketim** (tüketilen − geri kazanılan), `regenKwh` pozitif;
  brüt = net + rejen. Grafiklerde bu yığılmış bar olarak gösteriliyor.
- **Sapma oranı 1,0'ın üstündeyse gösterge iyimser**, altındaysa kötümser.
- **Eksik alan sıfıra çevrilmiyor.** Araç o property'yi vermediyse değer "—"
  görünüyor ve grafikte o nokta hiç çizilmiyor; ortalamalara da girmiyor.
- **GPS mesafesi ile tekerlek mesafesi ayrı tutuluyor** (şema 3). İkisinin oranı
  GPS hatasının tek ölçüsü, o yüzden kendi grafiği var.

Birden çok dışa aktarım aynı anda açılabilir (çoklu seçim, klasör ya da
birbirinin üstüne eklenen kaynaklar). Aynı yolculuk iki dosyada varsa
`startEpoch` ile tekleniyor; şeması yeni ve alanı daha dolu olan kopya
tutuluyor, böylece eski bir yedek yeni kaydı ezmiyor. Okunamayan dosya bütün
yüklemeyi düşürmüyor, durum çubuğunda sayısı yazıyor; yeni bir kaynak hiç
okunamazsa ekranda duran kayıtlara dokunulmuyor.

## CSV

**Dosya → Tabloyu CSV'ye aktar** filtrelenmiş kümeyi yazar, kodlama UTF-8 BOM.
Biçim arayüz diline göre: Türkçede ayraç `;` ve ondalık virgül, İngilizcede `,`
ve ondalık nokta, tarih ISO (`2026-09-15 08:02:12`). Excel ayracı sistemin yerel
ayarından okuduğu için her iki durumda da çift tıklayınca sütunlar ve sayılar
doğru ayrılıyor; başlıklar da seçili dilde.

## Klasör düzeni

```
ex30trips/
  model.py    Trip / PerfRecord — trip/Trip.kt'nin Python karşılığı
  loader.py   dosya okuma, klasör tarama, kaynakları birleştirme/tekleme
  drive.py    Drive protokol 3: REST ağ katmanı, artımlı eşitleme, hesap önbelleği, iz indirme
  auth.py     Google girişi: loopback + PKCE, DPAPI'li token, yenileme, çıkış
  track.py    GPS izi ayrıştırma + iz CSV'si
  stats.py    toplamlar; TripStats.kt ile aynı tanımlar
  charts.py   matplotlib çizimleri, Rota dahil (pencereyi tanımaz)
  theme.py    tek renk paleti: ttk + matplotlib
  i18n.py     dil seçimi, t(), sayı/tarih/süre/CSV biçimleri
  lang/       tr.py + en.py — metin tabloları
  settings.py kalıcı tercihler (dil)
  app.py      Tkinter penceresi
main.py       PyInstaller giriş betiği (paket mantığı ex30trips'te)
araclar/      ikon üretici, ortam denetleyici, OAuth istemcisini gömen oauth-gom.py
assets/       ex30.ico + önizleme
ornek/        araçtan çıkmış örnek dışa aktarım
screenshots/  README görselleri
tests/        birim testleri
```

`charts.py` Tkinter'ı hiç tanımıyor: çizimler `Figure` alıp ona çiziyor, bu
yüzden pencere açmadan PNG'ye basılabiliyor ve test edilebiliyor.

## Test

```
py -3 -m unittest discover -s tests
```

83 test: gerçek örnek dosyanın okunması, eksik alanların None kalması, şema 1
uyumluluğu, birleştirmede zengin kopyanın kazanması, bozuk dosyanın yüklemeyi
düşürmemesi, kaynakların birikmesi, enerji ağırlıklı ortalama ve mesafe
ağırlıklı menzil sapması.

Drive testleri ağa çıkmıyor. `FakeDrive`, Drive REST v3'ün okuma uçlarının
bellekteki karşılığı: gerçek `HttpApi`'nin istek adreslerini ve `q` sorgusunu
çözüp gerçek JSON gövdesi döndürüyor; sahte ile gerçek istemci arasında
yalnızca HTTP yok.

- **Ağ katmanı (DriveApiTests):** `files.list` satırlarının çözümlenmesi
  (tanınmayan satır atlanıyor), **sayfalama** (`nextPageToken`), RFC 3339
  imleçli sorgu, `alt=media` + **MD5 denetimi**, **401 → yenile + bir kez
  tekrar** (yenisi de reddedilirse yeniden giriş, sonsuz döngü yok), 403
  `insufficientPermissions` → token unutuluyor, 429 / hız sınırında geri
  çekilme, 404 ve Drive'ın hata iletisinin aktarılması.
- **Eşitleme (SyncTests):** ilk eşitlemede tam liste ve imleç, sonrakinde
  **imleç − 5 dk**, örtüşmede geç görünen dosyanın kaçmaması, aynı dosyanın
  **`ex30id` ile teklenmesi**, bir özet inmezse **imlecin ilerlememesi** ve
  yalnızca kalanın yeniden denenmesi, liste hatasında hiçbir şeyin değişmemesi,
  **MD5 tutmazsa eldekinin ezilmemesi**, **günlük tam tarama kararı** ve "baştan
  tara", tam listede çöpe atılan izin unutulması, iz indirme ve "iz yok"un ağa
  çıkmadan bilinmesi, hesap başına İstanbul saatine göre ay klasörü.
- **Giriş (AuthTests):** tarayıcı taklidiyle baştan sona loopback + PKCE
  girişi, **Drive kutusu boşsa girişin reddi**, DPAPI ile şifreli saklama,
  yenileme ve **`invalid_grant` → token'ın silinmesi**, yenilemede izin
  denetimi, çıkışın yalnızca o hesabın önbelleğini silmesi.
- **Geçiş (MigrationTests):** sürüm 2 ayarının ve önbelleğinin **bir kez**
  silinmesi, dil ayarının ve hesap önbelleklerinin kalması.

İz testleri (TrackTests): ayrıştırma, sütun sırası değişse de aynı değerler,
bilinmeyen sütun ve sürüm, başka yolculuğun izi, gzip, `dist_m` yoksa konumdan
mesafe, iki dilde iz CSV'si. Tek nesne özetin (kendi `records` alanıyla)
tek yolculuk okunması. Rota grafiği iki dilde, üç renk seçeneğiyle; dolu, kısa,
konumsuz, boş ve iz yokken PNG'ye çiziliyor; bağlı eksenler ve haritadaki
vurgu da sınanıyor.

Dil testleri (I18nTests): iki tablonun anahtar ve yer tutucu eşitliği, koddaki
her anahtarın tabloda olması, iki dilde sayı/tarih/süre/CSV biçimleri, çoğul
seçimi, hata mesajlarının `str()` anındaki dilde çıkması, açılış dili önceliği
ve **her grafiğin iki dilde, dolu ve boş veriyle gerçekten PNG'ye çizilmesi** —
çeviri çağrıları çizim sırasında çalıştığı için hata ancak orada görünüyor.

Eksen testleri (ChartAxisTests): iki dilde, her grafikte, çok günlük / iki
günlük / tek günlük veride ve yakınlaştırılmış eksende hiçbir etiketin
yinelenmemesi. Tarih ekseninde etiketin ayrıntısı (gün, saat, gün+saat, ay)
verinin yayıldığı aralıktan değil **tiklerin gerçek aralığından** seçiliyor;
yolculuk başına barlarda aynı güne düşen iki yolculuk saatle ayrılıyor.

## Lisans

Copyright (C) 2026 Anıl Erke

Bu program özgür yazılımdır: Özgür Yazılım Vakfı tarafından yayımlanan **GNU Genel
Kamu Lisansı**'nın 3. sürümü ya da (tercihinize göre) daha sonraki bir sürümü
koşulları altında yeniden dağıtabilir ve/veya değiştirebilirsiniz
(`GPL-3.0-or-later`).

Bu program faydalı olması umuduyla dağıtılmaktadır, ancak **HİÇBİR GARANTİSİ
YOKTUR**; SATILABİLİRLİK veya BELİRLİ BİR AMACA UYGUNLUK zımni garantisi dahi
yoktur. Bağlayıcı olan, [LICENSE](LICENSE) dosyasındaki İngilizce tam metindir.

Kısacası: bu kodu kullanabilir, inceleyebilir, değiştirebilir ve paylaşabilirsiniz.
Değiştirilmiş bir sürümü dağıtırsanız (uygulama mağazasında yayınlamak dahil),
onun kaynak kodunu da aynı lisansla açmanız gerekir.
