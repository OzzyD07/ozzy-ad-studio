# OtoReklam v2 — Yol Haritası

Hedef: tek MiniMax video hattından **çok yönlü sosyal medya üretim aracına** geçmek. Aynı sistemden AI videolar,
Remotion şablon videoları, görsel postlar ve carousel'ler çıkacak; günde 2 gönderi rahatça yayınlanabilecek.

Durum işaretleri: `[ ]` yapılacak · `[~]` sürüyor · `[x]` bitti · `[-]` iptal.
Akışın kuralları: [AKIS.md](AKIS.md). Alınan kararlar: [KARARLAR.md](KARARLAR.md).

## Mimari özeti

| Katman | Nerede | Görev |
|---|---|---|
| Studio MCP | Colab G4 (GPU) | MiniMax H3 Ref2VA FP8 video, Qwen 2.1 Image Turbo FP8 görsel; asenkron iş kuyruğu |
| Ses | Yerel PC (CPU) | Kokoro-82M seslendirme (Türkçe gerekirse Piper) |
| Kurgu | Yerel PC | Remotion: video şablonları, altyazı, end card, post/carousel görselleri |
| Orkestrasyon | Yerel PC | OtoReklam (Python): strateji, plan, iş kuyruğu, teslim |
| Depolama | Drive + GitHub | Model ağırlıkları Drive'da, kod GitHub'da; Colab ilk hücrede ikisini doğrular |

---

## Faz 0 — Temel `[x]`
- [x] Yayınlanmış videolar ve geçici çıktılar temizlendi (Geri Dönüşüm Kutusu)
- [x] `.gitignore` medya ve yerel ayarları dışlayacak şekilde yenilendi
- [x] Planlama akışı kuruldu (`docs/plan/`, `CLAUDE.md`)
- [x] `git init` ve ilk commit
- [x] Kampanya verisi (`workspace/`) repodan ve geçmişten çıkarıldı (K-13)
- [x] GitHub: `OzzyD07/ozzy-ad-studio` `origin` olarak bağlandı ve push edildi

## Faz 1 — Remotion kurulumu `[x]`
Bitti sayılır: `remotion/` içinden üç kompozisyon da örnek props ile Python'dan render alınır ve çıktılar incelenir.
- [x] Remotion lisansı: ücretsiz kullanım (K-12)
- [x] Doğrulama: `remotion_smoke.py` dört kompozisyonu render eder; kareler incelendi; `tests/test_render.py`
- [x] `remotion/` TypeScript projesi (Remotion 4.0.536, React 18.3.1; `npm ci`, `setup.ps1` kurar)
- [x] Marka teması: `theme` props + `config.theme`/`app.json`; Montserrat/Inter (latin-ext); ikon ve kırpılmış rozetler ayarlardan
- [x] `AdVideo`: AI klipleri + geçişler + 7 altyazı stili + hook metni + end card (`media.py` ile aynı görünüm)
- [x] `TemplatePromo`: AI'sız video (ekran görüntüsü / kayıt + kinetik tipografi + seslendirme)
- [x] `PostStill` ve `Carousel`: `renderStill` ile PNG (boyut props ile)
- [x] `render.py` + `pipeline.py remotion SPEC`: varsayılanları doldurur, medyayı hazırlar, Node API ile tek bundle'dan render eder
- [x] Kalite profili: `video.crf`/`preset`/`audio_bitrate`, 30 fps, -14 LUFS (ölçüldü: -14.0)
- [-] Remotion agent skill'leri: şimdilik gerek görülmedi

## Faz 2 — Yerel ses (Kokoro) `[x]`
Bitti sayılır: bir senaryodan ses + kelime zamanlaması üretilir ve Remotion altyazısı bununla senkron çalışır.
- [x] `tts.py` + `pipeline.py seslendir`: Kokoro-82M CPU, ses listesi, hız, okunuş sözlüğü (`pronounce`), WAV + `.words.json`
- [x] Kelime zamanlaması: Kokoro'nun kendi token zamanları; Piper için Whisper + `align_script`
- [x] Piper `tr_TR` (dfki/fahrettin/fettah) kurulu ve test edildi, varsayılan kapalı (K-9)
- [x] Fon müziği + konuşmada kısılma Remotion'da (Faz 1, `Music` bileşeni); spec'te `voiceover.text` → ses + senkron altyazı, `fitToVoiceover`

## Faz 3 — Studio MCP v2 (Colab) `[~]`
Bitti sayılır: Colab'da açılan sunucu, OtoReklam'dan video ve görsel işi alıp sonucunu döndürür.
- [x] Araç seti: `generate_video`, `generate_image`, `upload_asset`, `get_job`, `list_jobs`, `cancel_job`, `retry_job`, `reorder_job`, `list_models`, `server_status`, `free_vram`
- [x] Asenkron iş modeli: submit → `job_id` → durum → imzalı sonuç bağlantısı; işler Drive'da, yeniden başlatmada tekrar sıraya girer
- [x] Sunucu kodu bu repoda: `studio-mcp/` (K-8); MiniMax motoru OzzyVision-Lab'dan taşındı (K-20)
- [x] Model yöneticisi, toplu çalışma (K-10): VRAM'de tek model; kuyruk tipe göre gruplanır, önce tüm video işleri,
      sonra VRAM temizlenip Qwen yüklenir ve tüm görseller üretilir. Aynı tip işler arasında model yeniden yüklenmez.
- [x] Kuyruk görünürlüğü: `get_job` sıradaki konumu ve "model değişimi bekleniyor" durumunu döndürür
- [x] "Max kalite" ön ayarı: 10 adım, sabit seed seçeneği, `ref_image_size=max` (2048 px referans)
- [x] Qwen için varsayılan "yazısız" negatif prompt (metin/logo Remotion'da eklenir)
- [x] Erişim: sabit ngrok domain'i + **zorunlu** bearer token (Colab Secrets); adres repoya yazılmaz (K-11)
- [x] Mevcut `generate_omni_video` / `get_job` / `upload_asset` uyumluluğu: OtoReklam istemcisi `config.json` değişmeden test edildi
- [x] Testler: sahte ComfyUI ile uçtan uca 12 test (`studio-mcp/tests`)
- [~] **Colab'da canlı doğrulama (G4, RTX PRO 6000 96 GB):** Qwen görseli 14 sn'de üretildi, yazısız ve temiz; MiniMax videosu sürüyor
- [x] Qwen 2.1 Turbo: resmi şablon (8 adım sabit, cfg 1); kalite = çözünürlük (draft 1 MP … max 4 MP)

## Faz 4 — Colab notebook ve senkron `[~]`
Bitti sayılır: yeni bir Colab oturumu tek "Hepsini çalıştır" ile güncel kod + doğrulanmış modellerle ayağa kalkar.
- [x] Hücre 1: Drive bağla; Drive'daki kod (`MyDrive/OzzyAdStudio/code`) GitHub ile karşılaştırılır, yeniyse güncellenir
- [x] `studio-mcp/models.json`: dosyalar + boyut + sha256; eksikler **Drive'a** iner, `extra_model_paths.yaml` ile ComfyUI'ye bağlanır (K-23). Qwen 2.1 Turbo bf16 indirildi
- [x] Hücre 2: ComfyUI + bağımlılıklar
- [x] Hücre 3–4: modeller, ComfyUI + Studio MCP + sabit ngrok adresi; hücre 4 sunucuyu güncel kodla yeniden başlatır
- [ ] Oturum düşerse kaldığı işleri raporlama
- [ ] Yerel `workspace/apps` için Drive yedeği (K-13)

## Faz 5 — OtoReklam entegrasyonu `[ ]`
Bitti sayılır: tek plandan dört içerik tipi de üretilip teslim klasörüne düşer.
- [ ] İçerik tipleri: `ai_video`, `template_video`, `image_post`, `carousel`
- [ ] `config.json`: tek MCP içinde video + görsel araç eşlemeleri
- [ ] Strateji/plan: yeni formatlar için brif ve şablon seçimi
- [ ] Bir AI klibinden birden çok kurgu (farklı hook, süre, altyazı stili)
- [ ] `media.py` montaj/altyazı/end card işinin Remotion'a taşınması (eski yol yedek kalır)
- [ ] Testler (`tests/`) ve `smoke_test.py` yeni akışa göre

## Faz 6 — Günlük 2 gönderi akışı `[ ]`
Bitti sayılır: 14 günlük takvim, GPU bütçesine uygun format karışımıyla otomatik planlanır.
- [ ] Takvim üretici: gün başına 2 slot, format karışımı kuralları
- [ ] GPU bütçesi: günlük AI video/görsel sayısı sınırı
- [ ] Pano (`pano`) ve teslim (`teslim`) tüm formatları gösterir
- [ ] Platform açıklamaları (Instagram, TikTok, YouTube) her format için

---

## Açık sorular
| # | Soru | Neden önemli | Durum |
|---|---|---|---|
| S1 | Remotion'ı kullanacak şirket 3 çalışandan büyük mü? | Büyükse ücretli company license gerekir | kapandı: tek kişi, ücretsiz lisans (K-12) |
| S2 | GitHub repo adı ve özel mi olacak? | Faz 4'te Colab buradan çekecek | kapandı: "Ozzy Ad Studio" (`ozzy-ad-studio`), public (K-8) |
| S3 | Studio MCP kodu bu repoda mı (`studio-mcp/`) yoksa ayrı repoda mı? | Colab'ın klonlayacağı içerik | kapandı: bu repoda (K-8) |
| S4 | Türkçe seslendirme gerekecek mi? | Kokoro Türkçe desteklemiyor | kapandı: şimdilik hayır, Piper hazır kurulur (K-9) |
| S5 | Colab G4 VRAM'i iki modeli aynı anda tutmaya yetiyor mu? | Model yöneticisi tasarımı | kapandı: gerek yok, toplu sıralı çalışma (K-10) |
| S6 | Sabit tünel (ngrok static domain / Cloudflare Tunnel) var mı? | Her oturumda `mcp.url` değişmesin | kapandı: sabit ngrok domain'i var (K-11) |
| S7 | Public repoda kampanya verisi (`workspace/apps/`) ve iş kayıtları yer alsın mı? | Promptlar, araştırma ve MCP adresi herkese açılır | kapandı: hayır, yerelde + Drive yedeği (K-13) |
