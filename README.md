# Shortcut Video Downloader

iPhone'da kopyaladigin video URL'sini bir Kestirme ile internette calisan servise gonderip video dosyasi olarak geri almak icin hazirlanmis proje.

Bu surum bilgisayara, ayni Wi-Fi agina veya sana ait bir domaine bagli degil. Servisi bir cloud hosting'e koyarsin; hosting sana otomatik public URL verir. iPhone kestirmesi bu URL'nin `https://.../api/download` adresini arka planda cagirir.

Eski `R⤓Download` kestirmesine benzer sekilde kullanici tarafinda tek is kopyalanan/paylasilan URL ile kestirmeyi calistirmak. Kaydetme davranisi ilk kurulumda `Auto Save = 1` veya `Show Content = 2` olarak secilir.

## Ne yapar?

- iPhone Kestirmesi URL'yi panodan veya Paylas menüsünden alir.
- URL'yi cloud'daki servise gonderir.
- Servis `yt-dlp` ve `ffmpeg` ile videoyu indirip gerekirse MP4'e birlestirir.
- Video dosyasini iPhone'a geri dondurur.
- Kestirme videoyu Fotograflar'a veya Dosyalar'a kaydeder.

## Dosyalar

- `server.py`: Web servisi
- `Dockerfile`: Cloud/container deploy icin
- `SHORTCUT.md`: iPhone Kestirme kurulumu
- `CLOUD.md`: Cloud'a koyma notlari
- `run.ps1`: Yerelde test etmek icin
- `tests/test_server.py`: Basit testler

## Cloud'a koyma

Docker destekleyen bir web service/container hosting kullan. Kendi domain'in olmasi gerekmez; hosting sana otomatik public URL verir.

Deploy edilen servis icin su endpoint gerekir:

```text
https://HOSTINGIN-VERDIGI-URL/api/download
```

Detaylar [CLOUD.md](CLOUD.md) dosyasinda.

## iPhone Kestirmesi

Kestirme adimlari [SHORTCUT.md](SHORTCUT.md) dosyasinda.

Kestirmede URL olarak sunu kullan:

```text
https://HOSTINGIN-VERDIGI-URL/api/download
```

## Yerelde test

PowerShell'de:

```powershell
.\run.ps1
```

Saglik kontrolu:

```powershell
curl http://localhost:8787/health
```

Video indirme testi:

```powershell
curl -X POST http://localhost:8787/api/download -H "Content-Type: application/json" -d "{\"url\":\"VIDEO_URL\"}" --output video.mp4
```

## Ayarlar

- `PORT`: Varsayilan `8787`
- `HOST`: Varsayilan `0.0.0.0`
- `REQUIRE_TOKEN`: Varsayilan `0`. `1` yaparsan token kontrolu acilir.
- `SHORTCUT_TOKEN`: `REQUIRE_TOKEN=1` ise beklenen token degeri.
- `MAX_FILESIZE`: Varsayilan `750M`
- `DOWNLOAD_TIMEOUT_SECONDS`: Varsayilan `900`
- `YTDLP_FORMAT`: yt-dlp format secimi
  - Varsayilan secim iPhone Photos icin H.264 (`avc1`) MP4'e oncelik verir.
- `MAX_CONCURRENT_DOWNLOADS`: Ayni anda kac indirmeye izin verilecegi. Varsayilan `2`
- `YTDLP_COOKIES_FILE`: Hosting icinde mevcut bir cookies.txt yolu
- `YTDLP_COOKIES_TEXT`: Netscape cookies.txt icerigi
- `YTDLP_COOKIES_BASE64`: Netscape cookies.txt iceriginin base64 hali
- `TRANSCODE_FOR_IOS`: Varsayilan `auto`. Yalnizca uyumsuz dosyalari dusuk kaynak
  kullanarak H.264/AAC MP4'e cevirir. `1` tum dosyalari cevirir, `0` kapatir.

Token ornegi:

```powershell
$env:SHORTCUT_TOKEN="uzun-bir-sifre"
.\run.ps1
```

## Sinirlar

- Bazi siteler giris, cookie veya ek dogrulama isteyebilir.
- Instagram Story ve private hesap linkleri genelde giris/cookie ister. Public Reel/Post linkleriyle test et.
- DRM, ozel/kapali hesaplar veya indirme iznin olmayan icerikler desteklenmez.
- Bu proje yalnizca sana ait, herkese acik veya indirme iznin olan videolar icindir.
