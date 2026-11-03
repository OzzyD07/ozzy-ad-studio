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
| K-7 | 2026-11-03 | Yayınlanmış MentorAi videoları ve ara çıktılar silindi; iş kayıtları ve planlar korundu | Hepsi paylaşıldı; repo hafif başlasın |
| K-8 | 2026-11-03 | Repo adı "Ozzy Ad Studio" (`ozzy-ad-studio`), public; Studio MCP sunucusu aynı repoda `studio-mcp/` altında | Colab tek repoyu token'sız klonlar; kod ve istemci birlikte sürümlenir |
| K-9 | 2026-11-03 | Türkçe ses için Piper kurulur ama varsayılan kapalı; aktif ses Kokoro (İngilizce) | Şimdilik Türkçe yok; ihtiyaç olunca hazır olsun |
| K-10 | 2026-11-03 | VRAM'de aynı anda tek model; işler tipe göre toplu: önce tüm videolar, sonra VRAM temizlenip tüm görseller | G4 iki modeli birlikte tutamayabilir; her işte yeniden yükleme süresi harcanmaz |
| K-11 | 2026-11-03 | MCP sabit ngrok domain'i üzerinden yayınlanır; adres yalnızca `config.json`'da durur, token zorunlu | Repo public olduğu için adres ve erişim korunmalı |
| K-12 | 2026-11-03 | Remotion ücretsiz lisansla kullanılır | Kullanıcı tek kişi, şirket yok; ücretsiz lisans kapsamında |
| K-13 | 2026-11-03 | `workspace/` (kampanya verisi, iş kayıtları, çıktılar) git'e girmez, geçmişten de silindi; yedeği Drive'a alınır | Public repoda promptlar, araştırma ve MCP adresi görünmesin |
