# Cloud'a koyma

Bu proje artik bilgisayarina veya sana ait bir domaine bagli kalmadan calisacak sekilde hazirlandi. Mantik:

1. Bu servisi Docker destekleyen bir hosting'e koyarsin.
2. Hosting sana `https://...` ile baslayan public bir URL verir.
3. iPhone Kestirmesi bu URL'ye video linkini yollar.
4. Servis videoyu indirip iPhone'a dosya olarak geri dondurur.

## Gereken hosting tipi

Serverless function yerine normal container/web service kullan. Video indirme ve donusturme islemi zaman alabildigi icin kisa zaman limitli serverless ortamlar uygun degil.

Hosting'de Dockerfile'i kullan:

```text
Dockerfile
```

Ortam degiskenleri:

- `PORT`: Hosting genelde otomatik verir. Vermezse `8787`.
- `SHORTCUT_TOKEN`: Mutlaka uzun bir sifre koy.
- `MAX_FILESIZE`: Ornek `750M`.
- `DOWNLOAD_TIMEOUT_SECONDS`: Ornek `900`.
- `MAX_CONCURRENT_DOWNLOADS`: Ornek `2`.
- `YTDLP_COOKIES_BASE64`: Sadece gerekirse, kendi hesabina ait cookies.txt iceriginin base64 hali.
- `TRANSCODE_FOR_IOS`: Varsayilan `1`. iPhone galerisine kayit icin acik kalsin.

## Cloud URL

Deploy bittikten sonra su endpoint'i kullanacaksin:

```text
https://HOSTINGIN-VERDIGI-URL/api/download
```

Saglik kontrolu:

```text
https://HOSTINGIN-VERDIGI-URL/health
```

Tarayicida form:

```text
https://HOSTINGIN-VERDIGI-URL/
```

## iPhone Kestirmesi icin

[SHORTCUT.md](SHORTCUT.md) dosyasindaki `https://HOSTINGIN-VERDIGI-URL/api/download` kismini hosting'in sana verdigi URL ile degistir.

`SHORTCUT_TOKEN` koyduysan Kestirme'de `URL'nin Icerigini Al` aksiyonuna header ekle:

- `X-Shortcut-Token`: hosting'deki token degeri

## Onemli not

Bu servis herkese acik internette duracagi icin token olmadan calistirma. Aksi halde baskalari senin servisinden video indirmeye calisabilir.

## Instagram Story / private icerikler

Instagram Story ve private hesap linkleri genelde giris ister. Cookie eklemeden cloud servis bunlari indiremez. En sorunsuz kullanim public Reel/Post linkleridir.

Cookie eklemek hesabin icin hassas bir islemdir. Bunu sadece kendi hesabin ve indirme iznin olan icerikler icin kullan. `SHORTCUT_TOKEN` guclu olmazsa baska biri senin servisinden senin oturumunla istek attirmaya calisabilir.
