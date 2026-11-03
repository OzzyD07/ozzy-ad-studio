# Karar kaydı

Her karar: tarih, ne seçildi, neden. Bir karar değişirse eskisi silinmez, "yerine K-x geçti" diye işaretlenir.

| # | Tarih | Karar | Neden |
|---|---|---|---|
| K-1 | 2026-11-03 | Remotion yerel PC'de render eder, Colab'da değil | GPU gerektirmez; Colab compute unit'i yalnızca model üretimine harcanır |
| K-2 | 2026-11-03 | Colab yalnızca GPU üretimi yapar (video + görsel), tek Studio MCP sunucusunda | Tek adres, tek token, tek iş kuyruğu |
| K-3 | 2026-11-03 | Kokoro-82M yerelde CPU ile çalışır | 82M parametre; CPU'da yeterince hızlı, Colab bağımlılığı azalır |
| K-4 | 2026-11-03 | AI modelleri yazısız/logosuz üretir; metin, logo ve rozetler Remotion'da eklenir | MiniMax'ta sahte logo/yazı sorunu yaşandı; görsel modellerde de aynı risk var |
| K-5 | 2026-11-03 | Model ağırlıkları Drive'da, kod GitHub'da; Colab ilk hücrede commit ve sha256 karşılaştırır | Ağırlıklar repoya sığmaz; kod sürümü tek kaynaktan gelir |
| K-6 | 2026-11-03 | MCP üretim araçları asenkron (submit → job_id → get_job) | Video üretimi ~20 dk, tek istek zaman aşımına düşer |
| K-7 | 2026-11-03 | Yayınlanmış MentorAi videoları ve ara çıktılar silindi; iş kayıtları ve planlar korundu. **Düzeltme:** K-13 sırasındaki geçmiş temizliği (`filter-branch`) iş kayıtlarını, revizyon JSON'larını ve takvimleri de sildi; `product.en.json`, `research.en.json`, iki plan notu, `app.json` ve ikon geri getirildi | Hepsi paylaşıldı; repo hafif başlasın |
| K-8 | 2026-11-03 | Repo adı "Ozzy Ad Studio" (`ozzy-ad-studio`), public; Studio MCP sunucusu aynı repoda `studio-mcp/` altında | Colab tek repoyu token'sız klonlar; kod ve istemci birlikte sürümlenir |
| K-9 | 2026-11-03 | Türkçe ses için Piper kurulur ama varsayılan kapalı; aktif ses Kokoro (İngilizce) | Şimdilik Türkçe yok; ihtiyaç olunca hazır olsun |
| K-10 | 2026-11-03 | VRAM'de aynı anda tek model; işler tipe göre toplu: önce tüm videolar, sonra VRAM temizlenip tüm görseller | G4 iki modeli birlikte tutamayabilir; her işte yeniden yükleme süresi harcanmaz |
| K-11 | 2026-11-03 | MCP sabit ngrok domain'i üzerinden yayınlanır; adres yalnızca `config.json`'da durur, token zorunlu | Repo public olduğu için adres ve erişim korunmalı |
| K-12 | 2026-11-03 | Remotion ücretsiz lisansla kullanılır | Kullanıcı tek kişi, şirket yok; ücretsiz lisans kapsamında |
| K-13 | 2026-11-03 | `workspace/` (kampanya verisi, iş kayıtları, çıktılar) git'e girmez, geçmişten de silindi; yedeği Drive'a alınır | Public repoda promptlar, araştırma ve MCP adresi görünmesin |
| K-14 | 2026-11-03 | Remotion 4.0.536 + React 18.3.1 sabit sürüm; render Node API ile (tek bundle, sonra renderMedia/renderStill) | En az 2 haftalık sürüm; carousel'de her slayt için yeniden bundle yok |
| K-15 | 2026-11-03 | Spec'te olmayan isteğe bağlı alanlar render.py'de `null` gönderilir | Remotion, Studio demo defaultProps'unu her render'a karıştırıyor; demo altyazısı gerçek videoya sızdı |
| K-16 | 2026-11-03 | Aktif kelime büyütmesi `transform` yerine font boyutuyla | Satır ASS'teki gibi yeniden akar; büyük kelime komşusunu örtmez |
| K-17 | 2026-11-03 | Resmi `kokoro` paketi (PyTorch, CPU) kullanılır; `kokoro-onnx` değil | Kelime zamanlarını yalnızca resmi paket veriyor; altyazı senkronu Whisper'sız olur |
| K-18 | 2026-11-03 | Seslendirme bağımlılıkları ayrı `requirements-tts.txt` (~1 GB), `setup.ps1 -Ses` ile isteğe bağlı | Disk dolu (%96); temel kurulum hafif kalsın |
| K-19 | 2026-11-03 | Spec'te `voiceover.text` verilince ses ve altyazı render sırasında üretilir | Tek dosyadan seslendirmeli video; ayrı ses/altyazı adımı gerekmez |
| K-20 | 2026-11-03 | Studio MCP her model için Python motoru kullanır; MiniMax motoru OzzyVision-Lab'dan (`VideoAi`) taşındı, eski proje olduğu gibi kalır | MiniMax grafiği referans sayısına göre düğüm değiştiriyor; sabit bağlama dosyası bunu ifade edemiyor. Çalışan mantık yeniden icat edilmedi |
| K-21 | 2026-11-03 | Çıktı dosyaları jetondan türetilen HMAC imzalı bağlantıyla sunulur | Mevcut istemci başlıksız indirir; dosyalar yine de korunur |
| K-22 | 2026-11-03 | MiniMax'ta negatif prompt etkisiz kabul edilir (CFG 1.0, BasicGuider) | Daha önceki "negatif prompt zayıf" gözlemi bundan; istenmeyen şeyler prompt içinde tarif edilmeli |
| K-23 | 2026-11-03 | Üretim modelleri (MiniMax H3, Qwen Image, ComfyUI ağırlıkları) yalnızca Drive'da durur; bilgisayara kurulmaz. Colab bunları Drive'dan ComfyUI'ye bağlar | Kullanıcı isteği; C: diski dolu. Bilgisayarda yalnızca küçük yerel modeller kalır: Kokoro, Piper, Whisper |
| K-24 | 2026-11-03 | Qwen Image 2.1 Turbo **bf16** (Comfy-Org resmi); FP8 Turbo resmi depoda yok | En yüksek kalite; G4'ün 96 GB VRAM'i yetiyor. Yer gerekirse int8 seçilebilir |
| K-25 | 2026-11-03 | Jeton Claude bağlayıcısı için URL'de (`/mcp?key=`) de kabul edilir; OtoReklam jetonu `.secrets/studio_token` dosyasından okur | Bağlayıcı formu başlık gönderemiyor; jeton repoya girmez ve onu kullanıcı yerleştirir |
| K-26 | 2026-11-04 | Format, senaryodaki `format` alanıyla seçilir; yeni formatlar ayrı `formats.py` modülünde, AI video akışı aynen kalır | Çalışan MiniMax hattı bozulmadan genişlesin |
| K-27 | 2026-11-04 | `run` her geçişte bir adım ilerletir (görsel gönder → sonraki geçişte indir + render) | Kuyruk GPU'yu beklerken bloklanmaz; Colab'daki toplu çalışma (K-10) bozulmaz |
| K-28 | 2026-11-04 | Remotion bitirme isteğe bağlı (`render.engine`), varsayılan FFmpeg; kesitler yalnız Remotion'da | Görünüm kullanıcı tarafından onaylanmadan mevcut çıktı değişmesin |
| K-29 | 2026-11-04 | Takvim modülü `takvim.py` (`calendar.py` değil); teslim ve pano anahtarı "tarih + slot" | `calendar` adı Python standart kütüphanesini gölgeler; tek gönderili eski planlar slotsuz çalışmaya devam eder |
| K-30 | 2026-11-04 | GPU bütçesi uyarıdır, engel değil; süre tahminleri ilk gerçek ölçümlerle güncellenecek | Plan yine yazılır; kullanıcı aşımı bilerek seçebilir |
