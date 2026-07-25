# iPhone Kestirmesi

Kestirme adi: **R-Download Cloud**

Bu akisi eski `R⤓Download` kestirmesine benzer tuttum: Paylas menüsünden, Safari'den, URL'den veya panodan link alir; cloud servisine yollar; sonuc gelince ilk kurulum ayarina gore otomatik kaydeder veya onizleme acar.

## Kurulumda sorulacak alanlar

Kestirmeye iki tane en ust `Metin` aksiyonu koy:

1. `Metin`
   - Deger: `1`
   - Ad: `SaveMode`
   - Import Question metni: `Auto Save = 1, Show Content = 2`

2. `Metin`
   - Deger: `https://HOSTINGIN-VERDIGI-URL/api/download`
   - Ad: `ServiceURL`
   - Import Question metni: `Cloud servis URL'si`

Cloud'da `SHORTCUT_TOKEN` kullaniyorsan ucuncu `Metin` aksiyonu ekle:

3. `Metin`
   - Deger: `TOKEN_DEGERIN`
   - Ad: `Token`
   - Import Question metni: `Servis token'i`

## Aksiyonlar

1. `Kestirme Girdisini Al`
2. `Eger Kestirme Girdisi Deger Iceriyorsa`
3. `Degiskeni Ayarla`
   - Ad: `VideoURL`
   - Deger: `Kestirme Girdisi`
4. `Aksi Halde`
5. `Panoyu Al`
6. `Degiskeni Ayarla`
   - Ad: `VideoURL`
   - Deger: `Pano`
7. `Eger VideoURL "http" icermiyorsa`
8. `Girdi Iste`
   - Soru: `Video URL'sini yapistir`
   - Tur: `URL`
9. `Degiskeni Ayarla`
   - Ad: `VideoURL`
   - Deger: `Saglanan Girdi`
10. `URL`
   - Deger: `ServiceURL`
11. `URL'nin Icerigini Al`
   - Yontem: `POST`
   - Govde Iste: `JSON`
   - JSON alani:
     - Anahtar: `url`
     - Deger: `VideoURL`
   - Header:
     - Anahtar: `X-Shortcut-Token`
     - Deger: `Token`
12. `Adı Ayarla`
   - Ad: `R-Download.mp4`
13. `Eger SaveMode 2 ise`
14. `Belgeyi Onizle`
15. `Aksi Halde`
16. `Fotograf Albumune Kaydet`
17. `Eger'i Bitir`
18. `Bildirim Goster`
   - `Video indirildi.`

Token kullanmayacaksan Header kismini ekleme. Public'e atacaksan token kullan.

## Paylasim menusune ekle

Kestirme ayarlarinda:

- `Paylasim Sayfasinda Goster`: Acik
- Kabul edilen turler: `URL`, `Metin`, `Safari Web Sayfalari`, `Uygulama Icerigi`

## Eski kestirmeden alinan fikir

Eski kestirme de ilk kurulumda kaydetme modunu soruyor, Share Sheet/Safari/URL/metin girdisi kabul ediyor, sonra indirilen dosyayi ya onizliyor ya Fotoğraflar'a kaydediyordu. Bu projede ayni kullanici deneyimini cloud servisiyle kuruyoruz; bilinmeyen ucuncu parti indirme servisine baglanmiyoruz.

## Not

Bu proje DRM veya giris gerektiren icerikleri asmak icin tasarlanmadi. Yalnizca sana ait, herkese acik veya indirme iznin olan videolar icin kullan.
