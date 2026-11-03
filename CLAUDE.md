# OtoReklam — ajan notları

Proje şu an **v2 dönüşümünde**. Her oturumun başında `docs/plan/YOL-HARITASI.md` dosyasını oku, aktif fazı (`[~]`)
bul ve `docs/plan/AKIS.md`'deki döngüyü uygula. Mimari seçimler `docs/plan/KARARLAR.md`'de; onlara aykırı bir şey
yapmadan önce kullanıcıya sor.

- Dil: dokümanlar ve kullanıcı mesajları Türkçe; kod tanımlayıcıları mevcut stile uyar.
- GPU üretimi (MCP `generate_*`) kullanıcı onayı olmadan başlatılmaz; videolar tek tek üretilir ve kareleri incelenir.
- `config.json` git'e girmez; yeni ayar eklerken `config.example.json`'u da güncelle.
- Üretilen medya (`YAYINA-HAZIR/`, `workspace/apps/*/exports|raw|review`) git'e girmez.
