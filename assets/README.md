# Reklam varlıkları

Bu klasördeki dosyalar render sırasında otomatik kullanılır; yoksa güvenli bir yedek devreye girer.

| Dosya | Ne işe yarar | Yoksa |
|---|---|---|
| `badges/app-store.png` | Apple'ın resmi "Download on the App Store" rozeti (siyah, PNG) | Rozet ASS ile çizilir (logosuz metin rozeti) |
| `badges/google-play.png` | Google'ın resmi "Get it on Google Play" rozeti (PNG) | Rozet ASS ile çizilir (logosuz metin rozeti) |
| `app-icon.png` | Uygulama ikonu (kare, en az 512×512); köşeleri otomatik yuvarlanır | Bitiş kartında ikon gösterilmez |
| `fonts/*.ttf` / `*.otf` | Altyazı yazı tipi; `config.json → subtitles.font` alanına font adını yazın | Arial Black |
| `music/*.mp3` | Fon müziği; `config.json → music.file` veya senaryoda `music` | Yalnızca MiniMax'ın kendi sesi |
| `refs/*.png` | Karakter/mekân referans görselleri; ürün dosyasında `look.references` | Referanssız üretim |
| `refs/*.mp4` | 2–15 sn hareket/trend referansı (`<Video N>`) veya montaja giren gerçek görüntü (`clip`, ör. ekran kaydı) | Strateji demo konsepti önermez |
| `refs/*.mp3` | 2–15 sn anlatıcı sesi (`voice`) veya müzik havası (`music`) | Model kendi sesini seçer |

Bu klasördeki rozetler 2026-10-29'da resmi kaynaklardan indirildi ve değiştirilmedi:
- `app-store.svg`: Apple Marketing Toolbox (`toolbox.marketingtools.apple.com/api/v2/badges/download-on-the-app-store/black/en-us`); `app-store.png` bu SVG'nin 1197×400 şeffaf PNG çıktısıdır (Edge headless ile).
- `google-play.png`: `play.google.com/intl/en_us/badges/static/images/badges/en_badge_web_generic.png` (646×250).

Yenilemek için resmi sayfalar:
- Apple: https://developer.apple.com/app-store/marketing/guidelines/ (Badge → "Download on the App Store")
- Google Play: https://play.google.com/intl/en_us/badges/

Rozet boyutu: tek bir boyut kullanılır. İki rozet de şeffaf kenar boşluğu kırpıldıktan sonra aynı yüksekliğe (varsayılan 118 px ≈ ekran yüksekliğinin %6'sı, `config.json → end_card.badge_height`) ölçeklenir, aralarında 28 px boşlukla ortalanır; satır 920 px'i aşarsa ikisi birlikte küçültülür. Kaynak PNG'ler en az 3 kat büyüklükte (≥ 350 px yükseklik) olmalı ki küçültme keskin kalsın. Mağazalar rozetlerin eşit boyutta gösterilmesini ister; birini büyük birini küçük koymayın.
