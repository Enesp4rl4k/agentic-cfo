# 0004 · Model sağlayıcıları gateway arkasında, seçim ölçümle

- **Durum:** Önerildi (2026-11-19); sahip kararı bekliyor (model anahtarı ve bütçe)
- **Kimin:** Sahip
- **Plan v11:** K4, C7; A3.7 (altın küme), A3.8 (ikinci sağlayıcı)

## Bağlam
Model çağrılarının hepsi `platform/model_gateway` üzerinden gidiyor (39 modül); tek sağlayıcı var (OpenAI, `langchain-openai`). LLM'li uçtan uca hiçbir koşu ölçülmedi: canlı denemeler model anahtarı olmadan koştu (G10). Hangi modelin bu işlerde (Türkçe anlatı, THP sınıflandırması, belge alanı çıkarma) daha iyi olduğu bilinmiyor.

## Karar
Gateway çok sağlayıcılı olur: en az iki sağlayıcı ve anahtarsız ortam için kayıtlı yanıtlarla çalışan bir test modeli. Hangi işin hangi modelle yapılacağı sezgiyle değil, her LLM işinin altın kümesindeki skorla seçilir: uydurma sayı (0 olmalı), güven kapısına düşme oranı, koşu başına maliyet, p95 gecikme.

## Sonuçlar
- Tek sağlayıcıya bağımlılık riski kalkar.
- Seçim ölçüme bağlanır; ölçüm için model anahtarı ve bir bütçe gerekir (sahip kararı).
- Anahtarsız CI kayıtlı yanıtlarla koşar; canlı karşılaştırma haftalık yapılır.

## Alternatifler
- **Tek sağlayıcıda kalmak:** ölçüm yine gerekir; sağlayıcı riski kalır.
- **Kendi modelini eğitmek ya da ince ayar:** işaretlenmiş binlerce örnek yok (plan v10 §10). Reddedildi.

## Kanıt
`backend/app/platform/model_gateway.py`, `backend/app/platform/model_catalog.py`; PLAN_V10 §14 G10–G12.
