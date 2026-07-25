# AI CFO Suite — Demo Kurulum Kılavuzu

**TechNova Yazılım A.Ş.** için hazırlanmış 12 aylık gerçekçi finansal veriyle uçtan uca demo.

---

## Ön Koşullar

- Docker Desktop (v24+)
- Python 3.11+ (seed script için)
- 4GB boş RAM

---

## 🚀 Tek Komutla Başlat

```bash
# 1. Repoyu klonla
git clone <repo-url>
cd agentic-cfo

# 2. Demo ortamını başlat (ilk çalıştırmada ~3-5 dakika)
docker-compose -f docker-compose.demo.yml up --build -d

# 3. Demo verisini yükle ve analiz et
pip install httpx rich
python demo/seed.py
```

Hepsi bu kadar. Tarayıcıda `http://localhost:3000` adresini açın.

---

## 🔑 LLM API Key (Opsiyonel ama Önerilen)

API key olmadan uygulama çalışır — finansal hesaplamalar, grafikler ve anomali tespiti
gerçek veriyle çalışır. Sadece AI narratifleri ve CFO Chat devre dışı kalır.

**DeepSeek (önerilen — ~$0.001/analiz):**
```bash
# .env.demo dosyasında şu satırı düzenleyin:
OPENAI_API_KEY=sk-your-deepseek-key-here
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com
```

**OpenAI GPT-4o:**
```bash
OPENAI_API_KEY=sk-your-openai-key-here
LLM_MODEL=gpt-4o
LLM_BASE_URL=
```

Key ekledikten sonra `docker-compose -f docker-compose.demo.yml restart backend worker`

---

## 📊 Demo İçeriği

### TechNova Yazılım A.Ş. — 2024 Finansal Özet

| Metrik | Değer |
|--------|-------|
| Yıllık Gelir | ~₺4.8M |
| Brüt Marj | ~%72 |
| Net Gelir | ~₺1.2M |
| Büyüme (YoY) | ~%38 |
| İşlem Sayısı | 163 |
| Analiz Dönemi | Ocak–Aralık 2024 |

### Öne Çıkan Analizler

- **P&L**: Aylık gelir trendi, EBITDA marjı, gider kategorileri
- **Nakit Akışı**: 12 aylık seri, mevsimsellik tespiti
- **Tahmin**: 3 senaryo (iyimser/baz/kötümser) + Monte Carlo
- **Bütçe Karşılaştırması**: Kategori bazında sapma analizi
- **Vergi Takvimi**: KDV, stopaj, kurumlar vergisi hesaplamaları
- **Anomali Tespiti**: Duplicate ödeme, olağandışı tutarlar
- **CEO Dashboard**: Çapraz risk analizi, stratejik öncelikler

---

## 🌐 Servis URL'leri

| Servis | URL |
|--------|-----|
| Frontend Dashboard | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| Health Check | http://localhost:8000/health |

---

## 📁 Demo Veri Yapısı

```
demo/
├── data/
│   ├── logo_tiger_2024.csv     ← Ana finansal veri (Logo Tiger formatı)
│   └── ...
└── seed.py                     ← Otomatik yükleme scripti
```

### Farklı Senaryo Yüklemek

```bash
# Sadece yükleme (analiz yok):
python demo/seed.py --skip-analysis

# Farklı dosya:
python demo/seed.py --file logo_tiger_2024.csv

# Farklı backend:
python demo/seed.py --api http://staging.example.com/api/v1
```

---

## 🛑 Durdurma ve Temizleme

```bash
# Durdur
docker-compose -f docker-compose.demo.yml down

# Durdur + veriyi sil (sıfırdan başlamak için)
docker-compose -f docker-compose.demo.yml down -v
```

---

## 🐛 Sorun Giderme

**Backend başlamıyor:**
```bash
docker-compose -f docker-compose.demo.yml logs backend
```

**"Connection refused" hatası:**
```bash
# Backend hazır olana kadar bekleyin (~30 saniye)
docker-compose -f docker-compose.demo.yml ps
```

**Seed script bulunamıyor:**
```bash
# Reponun kökünden çalıştırın
cd /path/to/agentic-cfo
python demo/seed.py
```

**Port çakışması:**
```bash
# 3000 veya 8000 portları kullanımda ise:
lsof -i :3000
lsof -i :8000
```

---

## 🏗️ Production'a Geçiş

Demo'dan production'a geçmek için:

1. `.env.demo` → `.env` kopyalayın
2. PostgreSQL şifresini değiştirin
3. `BACKEND_SECRET_KEY` gerçek bir secret ile değiştirin
4. `docker-compose.yml` (ana) kullanın
5. Reverse proxy (Nginx/Traefik) ekleyin

```bash
# Production
cp .env.demo .env
# .env içinde OPENAI_API_KEY, POSTGRES_PASSWORD, BACKEND_SECRET_KEY değiştirin
docker-compose up --build -d
```

---

*AI CFO Suite — Agentic Financial Intelligence Platform*
