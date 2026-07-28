# AI Prompt Radar

X üzerinde herkese açık olarak paylaşılan popüler yapay zekâ promptlarını, ücretli
X API anahtarı kullanmadan keşfetmeyi ve günlük olarak GitHub'da arşivlemeyi
amaçlayan otomasyon.

## Nasıl çalışır?

1. `config/queries.txt` içindeki Türkçe ve İngilizce sorguları anahtarsız çoklu
   web araması ve açık RSS sonuçlarında tarar.
2. Bulunan `x.com/.../status/...` bağlantılarını tekilleştirir.
3. Erişilebilen gönderileri anahtarsız herkese açık embed uç noktasıyla
   zenginleştirir.
4. Prompt olma ihtimali, güncellik ve etkileşim sayılarına göre puanlar.
5. Sonuçları `archive/YYYY/MM/YYYY-MM-DD.md` ve `.json` dosyalarına yazar.
6. GitHub Actions her gün otomatik çalışır ve yeni arşivi depoya işler.

> [!IMPORTANT]
> X'in resmi API'si kullanılmadığı için bu yöntem tüm X akışını eksiksiz
> tarayamaz. Arama motorlarının indekslediği ve herkese açık uç noktaların
> gösterebildiği gönderiler bulunabilir. Kaynak değişiklikleri zaman zaman
> sonuç sayısını düşürebilir.

## Elle çalıştırma

Python 3.11 veya daha yeni bir sürüm gerekir.

```bash
python -m pip install -r requirements.txt
python -m src.prompt_radar
```

Demo verisiyle:

```bash
python -m src.prompt_radar --fixture tests/fixtures/feed.xml --date 2026-07-28
```

## Ayarlar

| Değişken | Varsayılan | Açıklama |
|---|---:|---|
| `RADAR_MIN_SCORE` | `28` | Arşive girecek en düşük puan |
| `RADAR_MAX_ITEMS` | `50` | Bir günde kaydedilecek azami gönderi |
| `RADAR_TIMEOUT` | `20` | HTTP zaman aşımı (saniye) |
| `RADAR_QUERY_FILE` | `config/queries.txt` | Arama sorguları |
| `RADAR_EXTRA_RSS` | boş | Virgülle ayrılmış ek RSS adresleri |
| `RADAR_DISABLE_ENRICHMENT` | `0` | `1` ise gönderi zenginleştirmeyi kapatır |

Arama kapsamını değiştirmek için `config/queries.txt` dosyasını düzenleyin.
Satır başındaki `#` yorumdur.

## Günlük çalışma

`.github/workflows/daily.yml` her gün Türkiye saatiyle yaklaşık 09.15'te
çalışır. GitHub zamanlayıcısı UTC kullandığı ve Türkiye UTC+3 olduğu için
iş akışında `06:15 UTC` tanımlıdır. Actions ekranındaki **Run workflow**
düğmesiyle elle de çalıştırılabilir.

## Arşiv biçimi

Markdown sürümü insanlar için okunabilir liste üretir. JSON sürümü; gönderi
kimliği, kaynak bağlantısı, yazar, metin, etkileşim değerleri, puan ve
keşfedildiği sorguyu içerir. Daha önce görülen gönderiler `data/seen.json`
dosyasında tutulur.

## Sorumlu kullanım

Bu proje yalnızca herkese açık içerikleri indeksler. İçerik sahipliği
gönderinin yazarına aittir. Arşivde özgün X bağlantısı ve yazar bilgisi
korunur. Kaynakların kullanım şartlarına, robots kurallarına ve yürürlükteki
mevzuata uyulmalıdır.
