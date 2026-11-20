# 0005 · LangGraph yükseltmesi: önce yüzeyi küçült

- **Durum:** Önerildi (2026-11-19)
- **Kimin:** Geliştirici
- **Plan v11:** K5, C6; A3.3

## Bağlam
`langgraph==0.1.19` ve `langchain==0.2.17` sabitlenmiş durumda (`backend/requirements.txt`). Dosyadaki not, önceki sabitlemenin kurulamaz olduğunu ve testlerin 0.1.19 ile koştuğunu söylüyor. Bu sürümler eski; güvenlik yamaları ve yeni model desteği gelmeyecek. `langgraph`'ı 10 modül, `langchain`'i 2 modül doğrudan içe aktarıyor.

## Karar
Yükseltme tek bir PR'da yapılmaz. Önce bağımlılık yüzeyi küçültülür: graf kurma ve çalıştırma `platform/` altında tek bir modülün arkasına alınır, diğer modüller onu kullanır. Ölü ve az kullanılan ajan modülleri (A0.2, A3.5) temizlenir. Sonra yükseltme ayrı bir PR'da yapılır; altın testler ve eval'ler sabit kalır ve `pytest tests/test_agents/ -q` yeşil olmalıdır (CLAUDE.md #6).

## Sonuçlar
- Yükseltmenin dokunduğu yer tek modüle iner; davranış kayması tek yerde aranır.
- Yükseltme A3 fazına kadar bekler; o zamana kadar sürüm sabit kalır.

## Alternatifler
- **Hemen yükseltmek:** 10 modülde aynı anda API değişikliği olur ve ajan çıktısındaki kaymanın kaynağı bulunamaz. Reddedildi.
- **LangGraph'tan çıkmak:** orkestrasyon ve checkpoint yeniden yazılır; ölçülmüş bir sorun yok. Şimdilik reddedildi.

## Kanıt
`backend/requirements.txt` satır 9–17; `backend/app` altında `langgraph`'ı içe aktaran 10 dosya.
