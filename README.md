# OtoReklam

Windows üzerinde yerel reklam üretim hattı. Python 3.12, FFmpeg, Faster-Whisper ve MCP Python SDK kullanır.

> **v2 dönüşümü sürüyor** (Remotion, Kokoro, Colab Studio MCP: video + görsel). Plan ve ilerleme: [docs/plan/YOL-HARITASI.md](docs/plan/YOL-HARITASI.md).

Aktif MentorAi kampanyasında kullanıcı tercihi **yalnızca MiniMax H3**. `config.json` içindeki `model_policy=minimax_h3`, farklı üretim aracına geçişi engeller. OzzyVisionLab eşleştirmesi: üretim `generate_omni_video`, sorgulama `get_job`, çıktı `job.output_video`. Göreli video bağlantıları MCP sunucusunun adresine göre çözülür. Ngrok adresi değişirse `mcp.url` güncellenmelidir. İlk inceleme için yalnızca 19 ve 21 Ekim tarihli işler gönderildi; `run --wait` kalan işleri de gönderebileceği için bu ilk değerlendirme sırasında kullanılmamalıdır.

## Reklam kalitesi: neler var?

| Alan | Ne yapar |
|---|---|
| **Strateji** (`strategy`) | Ürün dosyasından konsept matrisi: 6 temel çerçeve (PAS, Önce/Sonra, POV, 3 neden, kamera karşısı anlatıcı, rutin) + **gündem/trend** (`research.json → trends`) + **gerçek uygulama demosu** (`assets/refs` içinde video varsa). Çerçeveler bağlayıcı değil: ajan her günü serbest konseptle (`"framework": "free"`) değiştirebilir, `strategy_hints.mix` ile çerçeve sırası, `strategy_hints.frameworks` ile kendi çerçeveleriniz eklenir. Brif `assets/refs` içindeki referans dosyalarını da listeler. Her konsepte A/B hook taslakları, 15 sn'lik MiniMax çekimlerine bölünmüş zamanlama ve kelime sınırları, platform güvenli alanları, test/ölçekleme kuralları. Çıktı: `workspace/apps/UYGULAMA/plans/strategy-TARİH.md/.json`. Senaryoları bu brife göre ajan (Claude) yazar. |
| **MiniMax H3 prompt motoru** (`minimax.py`) | Model sırası: `[Kamera hareketi]` + ana aksiyon → karakter → mekân/ışık/stil → `<Picture N>` / `<Video N>` / `<Audio N>` referans rolleri → `<d>[English] …</d>` seslendirme → kurallar. Kamera komutları: Push in, Pull out, Pan/Truck/Tilt/Pedestal, Zoom, Tracking shot, Static shot, Shake (en fazla 3 birlikte). |
| **Prompt denetimi** (`lint`) | Üretimden önce: marka adı `<d>` dışında mı (sahte logo kartı), konuşma süreye sığıyor mu (~2,6 kelime/sn), referans numaraları doğru mu, ekran/cihaz riski, doğrulanmamış iddialar (free, unlimited, therapy, #1…). `plan` hatalı promptla iş oluşturmaz. |
| **Çok çekimli reklam** | 30 sn = hook çekimi + gövde çekimleri. Gövde çekimi bir öncekinin **son karesini** (`<Picture N>`) ve **anlatıcı sesini** (`<Audio 1>`) referans alır: aynı kişi, oda, renk ve ses. `ref_image_size=max`, `quality=high`. |
| **Referanslı reklam** | Çekimin `references` listesine görsel (karakter, mekân, stil, ürün), **video** (`motion`: kamera hareketi, `action`: hareket/jest, `trend`: trend formatı; en fazla 3, 2–15 sn) veya **ses** (`voice`: anlatıcı tınısı, `music`: müzik havası) eklenir; dosya türü uzantıdan anlaşılır. Bir çekim **gerçek görüntü** de olabilir: `{"clip": "assets/refs/demo.mp4@0-6"}` üretilmeden montaja girer (ekran kaydı, ürün çekimi). Gerçek uygulama arayüzü yalnızca bu yolla gösterilir. |
| **A/B hook** | `hooks` listesindeki her açılış ayrı bir varyant (`…-A`, `…-B`) olur; gövde çekimleri paylaşılır, test başına yalnızca bir ek üretim. |
| **Montaj** (`edit` ve otomatik) | 2–3 klibi kırpma, `xfade` geçişleri (fade, slideup, zoomin, smoothleft… veya cut) ve ses çapraz geçişiyle birleştirir. Farklı oranlı klipler bulanık arka planla dikeye uyarlanır. |
| **Bitiş kartı** | Konuşma bitince görüntü bulanıklaşır; uygulama ikonu, adı, nabız atan CTA ve **App Store + Google Play rozetleri** kayarak gelir. Video 1,5 sn uzatılır, konuşma kesilmez. Resmi rozet PNG'leri `assets/badges/` içine konur: şeffaf kenar boşlukları otomatik kırpılır, iki rozet **aynı yüksekliğe** (118 px, `end_card.badge_height`) ölçeklenip ortalanır. Yoksa rozetler çizilir (bkz. `assets/README.md`). |
| **Altyazı** | Stiller: `pop`, `hormozi` (2 kelime, aktif kelime yeşil ve büyük), `box` (kutulu), `tiktok`, `neon`, `classic`. Marka adı, sayılar ve `emphasis` kelimeleri sürekli vurgulu. Üstte ilk 2,8 sn **metin kancası** (`hook_text`). Altyazılar bitiş kartında durur. |
| **Ses ve görüntü** | -14 LUFS ses normalizasyonu (sosyal medya standardı), isteğe bağlı fon müziği konuşmanın altında otomatik kısılır (sidechain), hafif keskinleştirme, oran yakınsa siyah bant yerine kadrajı doldurma. |

### Çok çekimli senaryo yazımı

`examples/product.multishot.example.json` tam bir örnektir. Ürün dosyasında `look` tüm çekimlerde tekrar edilen karakter/mekân/ışık tanımıdır (tutarlılık için şart); `look.references` karakter/mekân referans görselleri, `look.voice_reference` sabit anlatıcı sesi örneğidir (2–15 sn). Senaryo alanları:

- `hooks`: alternatif açılış çekimleri (her biri `duration`, `camera`, `visual`, `voiceover`, `hook_text`).
- `shots`: ortak gövde çekimleri; `transition` (bu çekime geçiş), `trim: [başlangıç, bitiş]`, `continuity: false` (süreklilik referansını kapatır), `speaker: "on_camera"` (dudak senkronlu konuşma), `beats` (çekim içi zaman çizelgesi), `references`.
- `emphasis`, `music`, `caption`, `cta`, `framework` (hangi çerçeve ya da `free`; sonuç karşılaştırması için).

Referanslı bir senaryo örneği:

```json
"shots": [
  {"duration": 6, "camera": ["Tracking shot"], "visual": "She walks into the kitchen and drops her bag.",
   "voiceover": "Exam week again.", "hook_text": "Exam week survival",
   "references": [{"file": "assets/refs/trend-walk.mp4", "role": "trend"}]},
  {"clip": "assets/refs/app-screen.mp4@0-6", "voiceover": "Three lines, one tap.", "transition": "slideup"},
  {"duration": 8, "camera": ["Push in"], "visual": "She closes the notebook and smiles.",
   "voiceover": "Try MentorAi tonight.",
   "references": [{"file": "assets/refs/calm-piano.mp3", "role": "music"}]}
]
```

Gerçek görüntü çekiminden sonraki üretim çekimi, süreklilik için ekran kaydını değil son **üretilmiş** çekimi referans alır. Gündem için `research.json` içine `trends: [{topic, angle, date, expires, source, checked_on}]` yazın; süresi geçen trend atlanır, tarihli olan kendi gününe yerleşir.

```powershell
.\run.ps1 --app mentorai strategy --start 2026-11-01 --days 7
.\run.ps1 --app mentorai lint
.\run.ps1 --app mentorai plan --start 2026-11-01 --days 7
.\run.ps1 --app mentorai run --limit 3 --wait
```

Kuyrukta çekimler (`…-ha`, `…-s2`) önce üretilir; süreklilik isteyen çekim, önceki çekimin videosu gelene kadar bekler. Tüm çekimler hazır olunca montaj işi (`…-A`) birleştirilir ve render edilir. Aynı gün + açı için iş zaten varsa `plan` onu korur.

### Kendi videolarını birleştirmek

```powershell
.\run.ps1 edit 'C:\videolar\hook.mp4@0.4-5.8' 'C:\videolar\demo.mp4' 'C:\videolar\son.mp4' --transition slideup --output '.\workspace\apps\mentorai\exports\montaj-1' --language en --script 'Tam seslendirme metni…' --cta 'Try MentorAi' --app mentorai --hook-text 'Your days are blurring together' --music '.\assets\music\calm.mp3'
```

`klip.mp4@başlangıç-bitiş` saniye cinsinden kırpar. `--app` verilirse bitiş kartında o uygulamanın adı, ikonu ve ayarları kullanılır (`--app-name` ile ad elle de verilebilir). `process` komutu da `--hook-text`, `--app-name`, `--music` seçeneklerini alır.

## Birden fazla uygulama

Her uygulama kendi klasöründe yaşar; planlar, işler ve videolar birbirine karışmaz:

```
workspace/
  apps/
    mentorai/                 ← uygulama kısa adı (--app mentorai)
      app.json                ← ad, ürün/araştırma dosyası, ayar farkları
      product.json, research.json
      analysis/  plans/  jobs/  raw/  exports/  review/  input/
      refs/                   ← süreklilik kareleri ve yükleme önbelleği
      assets/app-icon.png     ← bitiş kartı ikonu (varsa)
      assets/refs/            ← bu uygulamanın görsel/video/ses referansları
      assets/music/
  models/                     ← Whisper modelleri (ortak)
assets/badges, assets/fonts   ← mağaza rozetleri ve fontlar (ortak)
```

```powershell
.\run.ps1 new-app fitlog --name FitLog   # klasörü, product.json ve research.json şablonlarını oluşturur
.\run.ps1 apps                           # tüm uygulamalar ve iş sayıları
.\run.ps1 --app fitlog plan --days 7     # --product/--research verilmezse app.json'dakiler kullanılır
.\run.ps1 --app all status
.\run.ps1 --app all run --limit 3 --wait # uygulamaların kuyruklarını sırayla işler
```

Tek uygulama varsa `--app` yazmak gerekmez; birden fazlaysa zorunludur (veya `config.json → default_app`). `app.json → config` içine yazılan alanlar yalnızca o uygulama için genel ayarların üzerine yazılır, ör. `{"subtitles": {"style": "hormozi"}, "music": {"volume": 0.18}}`. Senaryodaki göreli dosya yolları (`assets/refs/yuz.png`, `clip`, `music`) önce uygulama klasöründe, sonra proje kökünde aranır. MentorAi'nin mevcut işleri `workspace/apps/mentorai/` altına taşındı; aktif İngilizce kampanya `analysis/product.en.json` dosyasını kullanır.

## Yayın panosu ve teslim

```powershell
.
un.ps1 --app mentorai pano                        # workspace/apps/mentorai/pano.html
.
un.ps1 --app mentorai sec 2026-11-02-435f28d9-B-r2 # o günün yayınlanacak videosunu seçer
.
un.ps1 --app mentorai teslim                      # seçili videoları ve açıklamaları teslim klasörüne koyar
```

- **Pano** (`pano.html`, tarayıcıda açılır): her gün için video, konsept, ekran metni, açıklama ve hashtagler, mağaza bağlantıları, ABD hedef saati ve Türkiye yayın saati.
  - "Açıklamayı kopyala" düğmesi metni platforma yapıştırılacak hâliyle kopyalar.
  - "Zamanlandı / Yayınlandı" kutucukları ve notlar o tarayıcıda saklanır.
  - Filtreler: yayına hazır, seçim bekliyor, üretimde, yayınlanmayanlar.
  - Pano iş dosyalarından üretilir. `sec` ve `teslim` her çalıştığında kendiliğinden yenilenir.
- **Seçim:** her gün için bir reklam seçilir. Revizyon işleri (`revisions/*/jobs/`) de seçilebilir; çekimler (shot) seçilemez.
- **Teslim:** her seçili gün için `NN_tarih/video.mp4` ve `aciklama.txt` oluşturur, özeti `teslim.json` dosyasına yazar.
  - Aynı dosyaya tekrar dokunmaz, hiçbir klasörü silmez. Planda karşılığı olmayan eski klasörleri yalnızca listeler.
- **Ayarlar** (`app.json`):
  - `"delivery_dir"`: teslim klasörü. Varsayılan `YAYINA-HAZIR/<uygulama>`; MentorAi için `YAYINA-HAZIR`.
  - `"publish"`: yayın saati, ör. `{"time": "19:00", "timezone": "America/New_York", "label": "New York", "local_timezone": "Europe/Istanbul"}`.
- **Saat dilimleri:** yaz saati geçişleri hesaplanır. ABD, Avrupa, Türkiye ve UTC dilimleri yerleşik. Diğer dilimler için `pip install tzdata` kurun.

## Menü

Komut ezberlemek gerekmez: `.\run.ps1` argümansız çalıştırılınca Türkçe bir menü açılır. Menü önce uygulamayı sorar, sonra şu adımları sunar:

- durum
- panoyu aç
- teslim
- kare tabloları
- prompt denetimi
- sıradaki işi üret
- sonuç içe aktar
- yeni plan

"Sıradaki işi üret" önce hangi işin gönderileceğini gösterir (`run --dry-run`), sonra onay ister.

## Revizyon, inceleme ve sonuçlar

```powershell
.\run.ps1 --app mentorai kareler                                  # indirilen kliplerin kare tabloları
.\run.ps1 --app mentorai incele 2026-11-09-f0cda708-ha red --not "ağız senkronu kayık"
.\run.ps1 --app mentorai revize 2026-11-09-f0cda708-ha --not "ağız senkronu" --ek "Keep the lips in sync with the words."
.\run.ps1 --app mentorai bol 2026-11-05-3b51ed3e 8+8              # 15 sn'lik çekimi iki devam eden parçaya böler
.\run.ps1 --app mentorai run --limit 1 --dry-run                  # neyin gönderileceğini gösterir, hiçbir şey göndermez
.\run.ps1 --app mentorai sonuc C:\indirilenler\tiktok-rapor.csv   # TikTok/Meta sonuçlarını içe alır
```

- **Kare tablosu:** her ham video indiğinde otomatik olarak `review/<iş>/sheet.png` oluşur (12 kare). Panodaki "İnceleme bekleyen klipler" bölümü bunları gösterir; onay ve red komutları tek tıkla kopyalanır. Kararlar iş dosyasındaki `review` alanına yazılır.
- **revize:** aynı promptla, isteğe bağlı tek satırlık ek talimatla `<iş>-rN` adında yeni bir deneme açar. Eski iş ve videosu korunur.
  - Değişen çekimi kullanan her montaj için de `-rN` kopyası açılır.
  - `--zincir`, o çekimden devam eden çekimleri de yeni klipten devam edecek şekilde yeniler.
- **bol:** bir çekimi `-rN-p1` / `-rN-p2` parçalarına böler.
  - Seslendirme cümle sınırından ayrılır; kelimeler sığmıyorsa komut reddeder.
  - İkinci parça birincinin son karesi ve sesiyle devam eder. Promptun zaman çizelgesi parçalara paylaştırılır.
  - Zaman çizelgesi yoksa `--gorsel2 "..."` ile ikinci parçada ne olacağını yazın.
  - Tek parça bir reklam bölünürse montajlı bir reklama dönüşür.
- **sonuc:** CSV satırları reklam adındaki iş kimliği veya tarihle (`2026-11-02`, `11-02`, `02.11`, `0211`) ve A/B harfiyle eşleştirilir. Eşleşmeyen satırlar yalnızca listelenir, tahmin edilmez.
  - Hesaplananlar: hook oranı (3 sn izlenme / gösterim), tutma oranı (ThruPlay veya 6 sn izlenme / 3 sn izlenme), CTR ve yükleme başı maliyet.
  - Öneriler planın eşiklerine göre çıkar: hook %25 altı → hook'u yenile; tutma %15 altı → gövdeyi kısalt; CTR %0,8 altı → CTA'yı değiştir; hepsi iyiyse ölçekle. 1.000 gösterimden önce karar verilmez.
  - Sonuçlar iş dosyasına ve panoya yazılır. Eşikler `app.json → "result_thresholds"` ile değiştirilebilir.
- **Platform metinleri:** `teslim` her güne `aciklama-tiktok.txt`, `aciklama-instagram.txt`, `aciklama-youtube.txt` ve `aciklama-ad.txt` dosyalarını da yazar.
  - TikTok ve Instagram açıklamalarında link tıklanmadığı için "App link in bio" yazılır.
  - YouTube'a `#Shorts` başlığı ve mağaza linkleri eklenir.
  - Reklam metni 100 karakteri aşmaz ve hashtag içermez.
  - Bir iş kendi `captions` alanıyla herhangi bir platform metnini elle belirleyebilir.

## Hızlı başlangıç

PowerShell'i bu klasörde açın:

```powershell
.\setup.ps1
.\run.ps1 doctor
```

PowerShell script çalıştırma politikanız engelliyorsa ayar değiştirmeden ` .\.venv\Scripts\python.exe pipeline.py doctor` şeklinde Python komutlarını kullanabilirsiniz. `setup.ps1` yeniden çalıştırıldığında mevcut config dosyasını korur.

### Hemen bir videoyu işlemek

```powershell
.\run.ps1 process 'C:\videolar\ham.mp4' --output '.\workspace\apps\mentorai\exports\ilk-reklam' --app mentorai --cta 'Hemen keşfet' --caption 'Uygulamanı keşfet: https://adresiniz'
```

Konuşma otomatik olarak Türkçe yazıya çevrilir. İlk kullanımda Whisper `small` modeli internetten indirilir; sonraki kullanımlarda `workspace/models` önbelleği kullanılır. CPU/int8 varsayılandır; CUDA kurulumu zorunlu değildir.

Hazır altyazı için `--srt 'C:\videolar\altyazi.srt'`; altyazısız çalışmak için `--no-subtitles` kullanın. Bu iki seçenek birlikte kullanılamaz. Sessiz videoda SRT veya açıkça `--no-subtitles` gerekir. CTA istemiyorsanız `--cta` vermeyin. CTA videoya gömülü bir görseldir; tıklanabilir reklam düğmesi platformda ayrıca ayarlanır.

Altyazılar Reels/TikTok tarzındadır: 1–3 kelimelik büyük harfli gruplar ekrana "pop" animasyonuyla gelir, konuşulan kelime renkli vurgulanır ve hafifçe zıplar. Whisper gerçek kelime zamanlarını kullanır; hazır SRT'de kelime zamanları satır içinde tahmin edilir. Stil `config.json` içindeki `"subtitles": {"style": "pop"}` ile seçilir: `pop` (sarı vurgu), `tiktok` (pembe-kırmızı vurgu), `neon` (yeşil parıltı) `hormozi`, `box` veya eski sade görünüm için `classic`. `end_card.enabled=true` iken CTA, uygulama adı ve mağaza rozetleriyle bitiş kartında gösterilir; `false` ise eski alttaki CTA kutusu kullanılır.

Her çıktı klasörü: `video.mp4`, `subtitles.srt`, `subtitles.ass`, `caption.txt`, `metadata.json`, `render.log`. Var olan çıktılar ezilmez. Dikey format 1080×1920, 30 fps; kaynak görüntü oranı korunarak boşluk eklenir. Ayarlar `config.json` içinde.

## Uygulamadan içerik takvimine

```powershell
.\run.ps1 new-app uygulamam --name 'Uygulamam'
.\run.ps1 --app uygulamam analyze 'C:\projeler\uygulamam'
```

Bu adım kod envanteri ve sınırlı metin örneklerini `workspace/apps/UYGULAMA/analysis/source-context.json` içine çıkarır; kendi başına LLM analizi veya web araştırması yapmaz. Gizli klasörler ve yaygın anahtar dosyaları atlanır; yine de dışarı paylaşmadan önce bağlamı inceleyin. Kaynak dosyalar değiştirilmez ve MCP'ye otomatik gönderilmez.

Birlikte çalışacağınız ajan (bu sohbette Codex) bu bağlamı ve uygulamayı inceleyip web araştırmasını yapar. `research-brief.md` görevi tanımlar. `examples/product.example.json` ve `examples/research.example.json` şemalarını `new-app` bunları `workspace/apps/UYGULAMA/product.json` ve `research.json` olarak kopyalar; gerçek verilerle doldurun. Örnekler gerçek araştırma değildir. İddialar kaynak kod/çalışan ürünle doğrulanmalı; kaynak tarihleri ve yaratıcı etkiler kaydedilmelidir.

```powershell
.\run.ps1 --app uygulamam plan --start 2026-10-19 --days 7
.\run.ps1 --app uygulamam status
```

Ürün dosyasında `language` (ör. `"en"`) ve elle yazılmış `scripts` listesi (`angle`, `hook`, `voiceover`, `visual`, `caption`) varsa plan bu senaryolardan İngilizce üretim istemleri kurar ve `workspace/apps/UYGULAMA/plans/plan-TARİH-DİL.md` okunabilir planını da yazar. İşteki `language`, render sırasında Whisper dilini ve altyazı büyük harf kuralını belirler. Aktif MentorAi İngilizce kampanyası: `workspace/apps/mentorai/analysis/product.en.json`; eski Türkçe işler `workspace/apps/mentorai/jobs/archive-tr/` altında (kuyruk alt klasörleri işlemez).

Günlük taslak takvim CSV'ye, üretim istemleri ve açıklamalar `workspace/apps/UYGULAMA/jobs/*.json` dosyalarına yazılır. Bu şablon tabanlı ilk taslaktır. Ajan/operatör üretimden önce istemleri, CTA ve açıklamaları düzenleyebilir. Aynı plan tekrar oluşturulunca mevcut işler korunur. Yeni planlar eskileri silmez; `status` ile kuyruğu inceleyin. Takvim tarihi yayın planıdır, video üretimini o tarihe kadar ertelemez.

## Remotion (şablon video ve görsel post)

`remotion/` bir Remotion 4 projesidir (sürümler sabit, `setup.ps1` içinde `npm ci` ile kurulur). Render yerelde, GPU'suz yapılır; ilk render Remotion'ın headless Chrome'unu indirir.

| Kompozisyon | Çıktı | Ne için |
|---|---|---|
| `AdVideo` | 1080×1920 MP4 | AI klipleri + geçiş + pop/hormozi altyazı + üst metin kancası + bitiş kartı (FFmpeg hattıyla aynı görünüm) |
| `TemplatePromo` | 1080×1920 MP4 | AI'sız tanıtım: kinetik başlıklar, telefon çerçevesinde ekran görüntüsü/kayıt, seslendirme, bitiş kartı |
| `PostStill` | 1080×1350 PNG | Tek görsel post: yazısız AI görseli + başlık, metin, CTA, ikon, rozetler |
| `Carousel` | slayt başına PNG | Instagram carousel: `01.png`, `02.png` …, sayfa göstergesi ve "kaydır" etiketi |

```powershell
.\run.ps1 --app mentorai remotion examples\remotion\post.json
.\run.ps1 --app mentorai remotion benim-spec.json --output workspace\out\reklam.mp4
cd remotion; npm run studio      # şablonları tarayıcıda canlı önizleme
.\.venv\Scripts\python.exe remotion_smoke.py   # dört kompozisyonu sentetik görüntüyle dener
```

Spec dosyası `{"composition", "props", "output"}` biçimindedir; örnekler `examples/remotion/` altında. Kurallar:

- Göreli medya yolları spec dosyasının klasörüne, bulunamazsa proje köküne göre çözülür. URL'ler olduğu gibi geçer.
- Başlık ve metinlerde `*kelime*` vurgu rengiyle yazılır (birden fazla kelime de olur: `*7 days*`).
- Spec'te verilmeyenler ayarlardan gelir: tema (`theme`), bitiş kartı (`end_card`: ikon, App Store/Google Play rozetleri kenar boşluğu kırpılmış olarak, `cta.text`, uygulama adı), geçiş (`edit`), altyazı dili (`whisper.language`), CRF/preset/ses bit hızı (`video`). Bitiş kartını kapatmak için `"endCard": null`.
- `AdVideo` klip süresi verilmezse dosyadan okunur. Video çıktıları FFmpeg ile -14 LUFS'a normalize edilir.
- Altyazı kelimeleri `{"text", "start", "end"}` (saniye). Whisper/`align_script` çıktısını dönüştürmek için `render.words_from_segments`.
- Uygulamanın renkleri `app.json` içinde: `"config": {"theme": {"primary": "#FE2C55", "highlight": "#FFE500", "background": "#0B0B12", "backgroundAlt": "#2A1640"}}`.

## İçerik formatları (Faz 5)

`product.json` senaryolarında `"format"` alanı akışı seçer (verilmezse eskisi gibi AI video). Tam örnek: `examples/product.formats.example.json`.

| format | Ne olur | Çıktı (`exports/<iş>/`) |
|---|---|---|
| (yok) / `ai_video` | MiniMax video → altyazı, hook, bitiş kartı. `config.json → "render": {"engine": "remotion"}` ile Remotion'da biter | `video.mp4` |
| `image_post` | `image_prompt` ile Qwen görseli (Studio MCP) → Remotion'da başlık/metin/CTA/ikon | `post.png` |
| `carousel` | `image_prompt` içeren her slayt için Qwen görseli → Remotion carousel; `"brand": true` slayta uygulama adı/ikon koyar | `01.png`, `02.png` … |
| `template_video` | GPU yok: Remotion `TemplatePromo` + Kokoro seslendirme (`promo.voiceover.text`) | `video.mp4` |

**Kesitler (`cuts`):** Bir AI klibinden birden çok bitmiş video, ör. `"cuts": [{"name": "video"}, {"name": "kisa", "trim": [0, 6], "hook_text": "POV: …", "caption_style": "hormozi"}]`. Her kesitin kendi kırpması, üst metni ve altyazı stili olur; ek GPU üretimi gerekmez (yalnızca `render.engine = "remotion"`).

`.\run.ps1 --app mentorai run` her geçişte işleri bir adım ilerletir: görseli gönderir, sonraki geçişte indirip render eder. Görsel ayarları `config.json → mcp`: `image_tool` (`generate_image`), `image_arguments`, `image_result_path` (`job.output_image`).

## Günde 2 gönderi (Faz 6)

```powershell
.\run.ps1 --app mentorai strategy --days 7 --per-day 2   # brif: her gün/slot için format önerisi + yazım rehberi
.\run.ps1 --app mentorai plan --days 7 --per-day 2       # senaryolar ikişer ikişer: sabah + akşam
.\run.ps1 --app mentorai run                              # her geçiş bir adım ilerletir
.\run.ps1 --app mentorai pano                             # gün + slot kartları; post ve carousel görsel olarak
.\run.ps1 --app mentorai teslim                           # YAYINA-HAZIR/NN_tarih_slot/
```

Ayarlar `app.json → "config": {"calendar": …}` (yoksa varsayılanlar): `per_day`, `slots` (ad, saat, formatlar; saatler `publish.timezone`'da), `budget` (`ai_videos_per_week`, `images_per_day`), `gpu` (süre ve işlem birimi tahminleri). `plan` dosyası "GPU bütçesi" bölümünde video/görsel sayısını, tahmini Colab süresini ve işlem birimini yazar; bütçe aşılırsa uyarır. Senaryoda `"slot"` verilirse o slot kullanılır. Görsel post ve carousel için açıklamalar Instagram gönderisi ve TikTok foto olarak yazılır (YouTube Shorts yok).

## Kampanya verisinin yedeği

`workspace/` git'e girmez (public repo), bu yüzden kampanya verisi ayrıca yedeklenir:

```powershell
.\run.ps1 yedekle                  # workspace/apps → zip; Colab açıksa Studio MCP ile MyDrive/OzzyAdStudio/backups
.\run.ps1 yedekle --yerel          # yalnızca yerel zip (workspace/backups)
.\run.ps1 yedek-geri drive         # Drive'daki en yeni yedeği workspace/restore altına açar
.\run.ps1 yedek-geri drive --uygula   # workspace/apps üzerine yazar (önce mevcut hâl yedeklenir)
```

Üretilmiş medya (`exports`, `raw`, `review`) ve 50 MB'tan büyük dosyalar zipe girmez. `config.json → backup`: `dir` (ikinci bir kopya klasörü, ör. `D:/Yedek/OtoReklam`), `keep` (yerelde tutulan yedek sayısı), `skip_dirs`, `max_file_mb`. Drive'da en yeni 30 yedek tutulur. Colab kapalıysa yerel zip yine yazılır, komut uyarı verir.

Colab'da hücre 3'teki `MODEL_CACHE` modelleri o oturum için yerel SSD'ye kopyalar (`minimax` ≈ 42 GB, `all` ≈ 75 GB); ilk yükleme ve video↔görsel geçişleri Drive'a göre hızlanır. Varsayılan `drive`: kopya yok, doğrudan Drive.

## Yerel seslendirme (Kokoro, Piper)

Seslendirme bilgisayarda, CPU ile yapılır. Kurulum ayrı ve isteğe bağlıdır (~1 GB): `.\setup.ps1 -Ses` veya `pip install -r requirements-tts.txt`. Modeller ilk kullanımda `workspace/models` altına iner (Kokoro ~330 MB).

- **Kokoro-82M** (varsayılan, İngilizce): kelime zamanlarını kendisi verir. Sesler: `.\run.ps1 seslendir --sesler` (ör. `af_heart`, `am_michael`, `bf_emma`, `bm_george`).
- **Piper** (Türkçe, varsayılan kapalı, K-9): `config.json → "tts": {"turkish": true}`. Zamanlamayı Whisper çıkarır, yazımı metinden alır (`align_script`).

```powershell
.\run.ps1 seslendir "Write one line a day." --ses am_michael --output workspace\ses\deneme.wav   # + deneme.words.json
.\run.ps1 --app mentorai remotion examples\remotion\voiceover-promo.json
```

Remotion spec'inde `"voiceover": {"text": "…", "voice": "af_heart", "speed": 1.0}` yazmak yeterli: ses üretilir, kelime zamanları altyazı olur (`"captions": null` ile kapanır, verilen `captions` ayarları korunur). `TemplatePromo` için `"fitToVoiceover": true` sahne sürelerini konuşmaya göre esnetir; bitiş kartı konuşma bitince gelir.

Ayarlar (`config.json` → `tts`): `voice`, `speed`, `turkish`, `piper_voice` ve `pronounce`. `pronounce` marka adlarının okunuşu içindir, ör. `{"MentorAi": "/mˈɛntɔɹ ˌAˈI/"}` (Kokoro fonem yazımı; altyazıda yazılış değişmez).

## MCP bağlantısı

`config.json` yerel bağlantı bilgilerini içerir ve Git dışında tutulur. Desteklenen bağlantılar: stdio ve Streamable HTTP. `mcp.command`/`args` veya `mcp.transport=http` ve `mcp.url` alanlarını doldurun. HTTP bearer anahtarı dosya yerine PowerShell ortam değişkeninden alınabilir:

```powershell
$env:VIDEO_MCP_TOKEN = 'ANAHTARINIZ'
.\run.ps1 mcp-tools
```

Araç şemaları `workspace/mcp-tools.json` dosyasına kaydedilir. `generate_tool` ve `generate_arguments` gerçek araç şemasına göre ayarlanır. `{{prompt}}`, `{{id}}` ve işteki diğer alanlar parametrelere yerleştirilir. Çağrıdan önce JSON Schema doğrulanır. `request_id` her sunucuda desteklenmez; şemaya göre kaldırın veya yeniden adlandırın.

`result_path` JSON yanıttaki yerel video yolunu veya HTTPS indirme URL'sini seçer (ör. `result.video_url`). Asenkron sunucu için `remote_id_path`, `status_tool` ve `status_arguments` ayarlanır. `{{remote_id}}` durum sorgusuna aktarılır. Düz metin JSON yanıtları ve structuredContent desteklenir. Farklı çıktı biçimleri/OAuth/özel indirme kimlik doğrulaması için gerçek sunucuya uyarlama gerekebilir; bağlantı verilene kadar canlı uyumluluk doğrulanamaz.

```powershell
.\run.ps1 --app mentorai generate IS_KIMLIGI
.\run.ps1 --app mentorai generate IS_KIMLIGI --poll
.\run.ps1 --app mentorai render IS_KIMLIGI
```

MCP olmadan üretilmiş videoyu kuyruğa bağlamak için:

```powershell
.\run.ps1 --app mentorai attach IS_KIMLIGI 'C:\videolar\ham.mp4'
.\run.ps1 --app mentorai render IS_KIMLIGI --srt 'C:\videolar\altyazi.srt'
```

### Toplu otomasyon

```powershell
.\run.ps1 --app all run --limit 3
.\run.ps1 --app all run --limit 3 --wait --interval 30 --timeout 3600
```

En fazla 3 tamamlanmamış işi bir geçişte işler: üretime gönderir, bekleyen işleri bir kez sorgular, hazır videoları indirip altyazı/CTA ekler ve açıklamayı kaydeder. Hazır SRT `workspace/apps/UYGULAMA/raw/IS_KIMLIGI.srt` adıyla verilebilir; aksi halde Whisper kullanılır. Sunucu işi beklemedeyse daha sonra aynı komutu tekrar çalıştırın. Bu komut ücretli video üretimini tetikleyebilir. Otomatik yayın yapmaz; sürekli çalışan servis/zamanlanmış görev kurulmaz.

`--wait` verilirse terminal açıkken 30 saniye aralıklarla kuyruğu tamamlamaya devam eder. `--limit` geçiş başınadır; bekleme modunda zaman içinde tüm kuyruk işlenebilir. `--timeout` geçişler arasındaki bekleme bütçesidir; devam eden MCP çağrısı veya renderı kesmez. Ctrl+C ile durdurulabilir; iş durumu diskte kalır.

Durumlar: `planned → submitting → waiting → raw_ready → done`. Ağ kesintisinde `submitting` kalırsa körlemesine tekrar üretim yapılmaz; sunucu tarafını kontrol edip `attach` ile devam edin veya sunucudan öğrendiğiniz `remote_id` ile durum sorgulayın. İndirme sonucu kaydedildiyse sonraki `run` üretimi tekrar çağırmadan indirmeyi dener. Her uygulamanın kendi kuyruk kilidi vardır. İşlem zorla kapandıysa, başka çalışan süreç olmadığını doğruladıktan sonra `workspace/apps/UYGULAMA/.queue.lock` dosyasını kaldırın.

Çıktıları yayınlamadan önce altyazı doğruluğu, ürün iddiaları, CTA ve platform güvenli alanları görsel olarak kontrol edin. `review_required` metadata alanı bu kontrolün henüz yapılmadığını gösterir.

## Doğrulama

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe smoke_test.py
```

Smoke testi sentetik video ve örnek SRT üretip gerçek FFmpeg renderı ve yerel deneme MCP sunucusunu (`generate_omni_video`, `get_job`, `upload_asset` taklidi) kullanır: tek çekimli iş, bitiş kartı (PNG rozet + ikon), iki hook varyantlı çok çekimli plan, süreklilik referansı yüklemesi ve montaj. Gerçek video ajanınızı veya ücretli servisi çağırmaz. Whisper model indirme/transkripsiyonu bu testin kapsamı dışındadır.

Doğrulanan kurulum `requirements.lock.txt` içinde sabitlenmiştir; `setup.ps1` bu sürümleri kurar. `requirements.txt` desteklenen sürüm aralıklarını belirtir. Kısıtlı ajan sandbox ortamı stdio alt sürecini engelleyebilir; uçtan uca test normal yerel süreç izinleriyle başarıyla çalıştırılmıştır.

Teknik kaynaklar: [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper), [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk). MCP SDK ana sürümü 1.x ile sınırlandırılmıştır.
