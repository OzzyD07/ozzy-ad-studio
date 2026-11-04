# Studio MCP (Colab)

Colab GPU'da çalışan üretim sunucusu: **video** (MiniMax H3 Ref2VA FP8) ve **görsel** (Qwen Image 2.1 Turbo FP8). Üretimi ComfyUI yapar; bu sunucu işleri sıraya alır, ComfyUI workflow'unu kurar, çıktıları Drive'a kaydeder ve MCP üzerinden sunar. OtoReklam ve Claude bu sunucuya bağlanır.

MiniMax tarafı OzzyVision-Lab'ın (`VideoAi`) çalışan motorundan taşındı: düğüm grafiği, referans bağlama, 17k+5 kare ızgarası, adım sayıları, 24 fps referans video hazırlığı, FP8 dosya seçimi.

## Araçlar

| Araç | Ne yapar |
|---|---|
| `generate_video` | MiniMax H3: 4–15 sn video + 32 kHz stereo ses; ≤9 görsel, ≤3 video (toplam ≤15 sn), ≤3 ses referansı |
| `generate_omni_video` | Eski ad, aynı araç (OtoReklam `config.json` değişmeden çalışır) |
| `generate_image` | Qwen Image: 1–4 görsel; 1:1, 4:5, 9:16, 16:9, 3:4, 4:3, 2:3, 3:2; varsayılan yazısız |
| `get_job`, `list_jobs` | Durum, sıra, tahmini bekleme, model değişimi bekleniyor mu, indirme bağlantıları |
| `cancel_job`, `retry_job`, `reorder_job` | Kuyruk yönetimi |
| `upload_asset`, `list_assets` | Referans yükleme (sunucu yolu, URL, base64) → `asset_id` |
| `list_models`, `server_status`, `free_vram` | Modeller ve sınırlar; GPU/VRAM, ComfyUI, kuyruk, disk; VRAM boşaltma |
| `save_backup`, `list_backups` | OtoReklam kampanya verisinin zip yedeği `backups/` altına (en yeni 30); imzalı indirme bağlantıları |

**Kuyruk (K-10):** VRAM'de aynı anda tek model türü durur. Video yüklüyken sıradaki videolar önce çalışır; tür değişince VRAM bir kez boşaltılır. Karışık kuyruk "önce bütün videolar, sonra bütün görseller" olarak işler. İşler Drive'da (`STUDIO_HOME/jobs`) tutulur; Colab yeniden başlarsa yarım kalan iş tekrar sıraya girer.

**Kalite:** `draft` / `standard` / `high` / `max`. MiniMax'ta 4 / 8 / 10 / 10 adım; `max` ayrıca referansları 2048 px'e kadar korur (`ref_image_size=max`). MiniMax CFG 1.0 ile çalışır, bu yüzden **negatif prompt etkisizdir**: istenmeyen şeyler prompt'un kendisinde tarif edilmeli (izinli eşya listesi, mekân). Qwen ön ayarları `QWEN_PRESETS` ile değiştirilebilir, ör. `{"max": {"steps": 16, "cfg": 1.0}}`.

**Güvenlik (K-11):** Her MCP isteği `Authorization: Bearer $STUDIO_TOKEN` ister. Çıktı bağlantıları (`/files/...?sig=`) jetondan türetilen imzayla korunur, başlık gerektirmez.

## Çalıştırma

ComfyUI `127.0.0.1:8188` üzerinde, modeller yüklü olarak çalışıyor olmalı (Faz 4 notebook'u bunu kuracak).

```bash
pip install -r studio-mcp/requirements.txt
cd studio-mcp
STUDIO_TOKEN=... STUDIO_HOME=/content/drive/MyDrive/OzzyAdStudio python -m studio.server   # :8000
ngrok http 8000 --domain=$NGROK_DOMAIN   # sabit domain Colab Secrets'ta; repoya yazılmaz (K-11)
```

| Ortam değişkeni | Varsayılan |
|---|---|
| `STUDIO_TOKEN` | zorunlu, en az 16 karakter (Colab Secrets) |
| `STUDIO_HOME` | `/content/drive/MyDrive/OzzyAdStudio` (jobs/, assets/, outputs/) |
| `COMFY_URL` | `http://127.0.0.1:8188` |
| `STUDIO_PORT`, `STUDIO_PUBLIC_URL`, `STUDIO_JOB_TIMEOUT` | `8000`, boş (göreli bağlantı), `5400` sn |
| `MINIMAX_DIFFUSION_MODEL`, `MINIMAX_TEXT_ENCODER`, `MINIMAX_VIDEO_VAE`, `MINIMAX_AUDIO_VAE` | ComfyUI'deki dosyalardan seçilir (FP8 önce) |
| `QWEN_UNET`, `QWEN_TEXT_ENCODER`, `QWEN_VAE`, `QWEN_PRESETS` | ComfyUI'deki dosyalardan seçilir (2.1 Turbo FP8 önce) |

OtoReklam tarafında `config.json → mcp`: `url` = `https://<domain>/mcp`, `token_env` = jetonun durduğu ortam değişkeni (ör. `VIDEO_MCP_TOKEN`).

## Test

GPU gerektirmez; sahte bir ComfyUI ile uçtan uca çalışır:

```bash
cd studio-mcp && python -m unittest discover -s tests
```
