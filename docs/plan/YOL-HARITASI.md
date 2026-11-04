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

## Faz 3 — Studio MCP v2 (Colab) `[x]`
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
- [x] **Colab'da canlı doğrulama (G4, RTX PRO 6000 96 GB):** Qwen görseli 14 sn, yazısız; MiniMax 4 sn taslak video 576×992, 32 kHz stereo, konuşma Whisper ile birebir doğrulandı. Canlıda bulunup düzeltilenler: `audio_vae` şema doğrulaması, logda jeton maskeleme, yeniden başlatmada sahipsiz ComfyUI istemi
- [x] Qwen 2.1 Turbo: resmi şablon (8 adım sabit, cfg 1); kalite = çözünürlük (draft 1 MP … max 4 MP)

## Faz 4 — Colab notebook ve senkron `[~]`
Bitti sayılır: yeni bir Colab oturumu tek "Hepsini çalıştır" ile güncel kod + doğrulanmış modellerle ayağa kalkar.
- [x] Hücre 1: Drive bağla; Drive'daki kod (`MyDrive/OzzyAdStudio/code`) GitHub ile karşılaştırılır, yeniyse güncellenir
- [x] `studio-mcp/models.json`: dosyalar + boyut + sha256; eksikler **Drive'a** iner, `extra_model_paths.yaml` ile ComfyUI'ye bağlanır (K-23). Qwen 2.1 Turbo bf16 indirildi
- [x] Hücre 2: ComfyUI + bağımlılıklar
- [x] Hücre 3–4: modeller, ComfyUI + Studio MCP + sabit ngrok adresi; hücre 4 sunucuyu güncel kodla yeniden başlatır
- [x] Oturum düşerse işler Drive'dan okunur, yarım kalan iş tekrar sıraya girer (canlıda görüldü)
- [x] Yerel `workspace/apps` için Drive yedeği (K-13, K-32): `pipeline.py yedekle` medya hariç zipler, Studio MCP `save_backup` ile `MyDrive/OzzyAdStudio/backups`'a yazar; yerel kopya `workspace/backups` (+ isteğe bağlı `backup.dir`); `yedek-geri` ile geri yükleme. Drive'a gönderim canlıda henüz denenmedi
- [x] Hız: hücre 3'te `MODEL_CACHE` = `drive` / `minimax` / `all` (K-31); seçilen modeller oturum için yerel SSD'ye kopyalanır, ComfyUI önce SSD'den okur. Gerçek süre kazancı ilk Colab oturumunda ölçülecek
- [ ] Notebook'taki geçici hücreyi silmek (kullanıcı yapacak; GitHub'daki sürümde yok)

## Faz 5 — OtoReklam entegrasyonu `[~]`
Bitti sayılır: tek plandan dört içerik tipi de üretilip teslim klasörüne düşer.
- [x] İçerik tipleri: `ai_video`, `template_video`, `image_post`, `carousel` (`formats.py`, plan + run)
- [x] `config.json → mcp`: `image_tool`, `image_arguments`, `image_result_path` (varsayılanlar kodda)
- [x] Plan yeni formatları okur; `strategy` brifi formatları Faz 6'daki takvimle öneriyor
- [x] Bir AI klibinden birden çok kesit (`cuts`: kırpma, hook, altyazı stili); bitiş kartı konuşmayı bekler
- [x] AI video bitirme Remotion'da (`render.engine = "remotion"`); FFmpeg yolu varsayılan/yedek. Çok çekimli montaj hâlâ FFmpeg
- [x] `tests/test_formats.py` (54 test); yerelde gerçek Remotion + Whisper ile post, şablon video ve 2 kesit denendi
- [ ] OtoReklam istemcisiyle canlı uçtan uca (Colab açık + `.secrets/studio_token`)
- [x] Varsayılan bitirme Remotion (K-33); `"render": {"engine": "ffmpeg"}` veya `--srt` eski yolu kullanır

## Faz 6 — Günlük 2 gönderi akışı `[x]`
Bitti sayılır: 14 günlük takvim, GPU bütçesine uygun format karışımıyla otomatik planlanır.
- [x] `takvim.py` + `plan/strategy --per-day 2`: slotlar (sabah/akşam), brif her gün/slot için format önerir
- [x] GPU bütçesi: haftalık video, günlük görsel sınırı + tahmini Colab süresi/birim plan dosyasında (süre tahminleri gerçek ölçümle güncellenecek)
- [x] Pano ve teslim gün+slot bazlı; post ve carousel görselleri gösterilir/kopyalanır (`NN_tarih_slot`)
- [x] Platform açıklamaları formata göre: görsel post/carousel için Instagram gönderi + TikTok foto (Shorts yok)

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
