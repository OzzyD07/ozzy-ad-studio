# Planlama akışı

Toplu değişim fazlara bölündü ([YOL-HARITASI.md](YOL-HARITASI.md)). Her iş aynı döngüden geçer:

1. **Seç** — Yol haritasında sıradaki `[ ]` maddeyi seç ve `[~]` yap. Aynı anda tek faz aktif olur.
2. **Dal aç** — `faz-N/kisa-ad` (ör. `faz-1/remotion-kurulum`). `main` her zaman çalışır durumda kalır.
3. **Yap** — Değişiklik + test. GPU harcayan üretimler kullanıcı onayı olmadan başlatılmaz.
4. **Doğrula** — Fazın "bitti sayılır" ölçütü gerçekten sağlanmalı (render alındı, kareler incelendi, testler geçti).
5. **Kaydet** — Maddeyi `[x]` yap; mimari bir seçim yapıldıysa [KARARLAR.md](KARARLAR.md)'ye ekle; açık soru
   kapandıysa tabloda "kapandı" yaz.
6. **Birleştir** — Kullanıcı onayıyla commit ve `main`'e merge; GitHub bağlıysa push.

## Commit mesajı
```
faz-1: Remotion AdVideo kompozisyonu

Kısa açıklama (neden).
```

## Ne nereye yazılır
| Bilgi | Yer |
|---|---|
| Yapılacaklar, ilerleme | `YOL-HARITASI.md` |
| Neden böyle yaptık | `KARARLAR.md` |
| Kullanım talimatı | `README.md` |
| Kampanya planları, iş kayıtları | `workspace/apps/<uygulama>/` |
