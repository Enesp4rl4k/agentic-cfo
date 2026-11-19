# 0002 · Karar günlüğü eklemeli; tam olay kaynaklama yok

- **Durum:** Önerildi (2026-11-19)
- **Kimin:** Geliştirici
- **Plan v11:** K2, C4; adımlar A1.6 (tablo ve çift yazma), A1.7 (geri doldurma), A2.1 (defter günlüğü uygular), A2.2 (G3)

## Bağlam
İnsan kararları türetilmiş tabloların içinde: olası mükerrer kararı defter satırının `ledger_status`'unda, eşleşme kararı `open_item_matches.status`'ta. Defter belgelerden yeniden kurulursa rakamlar aynı çıkar ama kararlar kaybolur (`docs/data-contracts.md`, "Bilinen boşluk"; G5). Bu yüzden bugünkü kural "defter tabloları elle silinmez".

## Karar
Kararlar kendi tablosunda, eklemeli tutulur: `decisions (id, org_id, tür, hedef_kimlik, karar, karar_veren, zaman, gerekçe, öncekinin_id)`. Bir kararı değiştirmek yeni bir satırdır; eskisi silinmez. Defter ve eşleşmeler belgeler artı bu günlük uygulanarak üretilir.

Sistemin geri kalanı olay kaynaklama (event sourcing) ile kurulmaz: belgeler, defter ve projeksiyonlar normal tablolarda kalır. Yalnız insan kararları ve (ADR 0001) yevmiye eklemelidir.

## Sonuçlar
- Defter silinip yeniden kurulabilir; kararlar geri gelir (değişmez I2, uygunluk testi F6).
- G3 bu günlükle kapanır: kategori düzeltmesi bir karar satırıdır.
- "Kim, ne zaman, neden karar verdi" sorusu tek tablodan cevaplanır.
- Tek seferlik bir geri doldurma gerekir (A1.7); tekrar çalıştırılabilir yazılır.

## Alternatifler
- **Tam olay kaynaklama:** her durum değişikliği bir olay olur, durum olaylardan türetilir. Değer kararların kaybolmamasında; geri kalanının maliyeti (olay şeması evrimi, yeniden oynatma süresi, iki ayrı model) karşılanmaz. Reddedildi.
- **Kararları türetilmiş tablolarda bırakıp yeniden kurulumda korumak:** her tabloya ayrı koruma mantığı gerekir ve kim/neden bilgisi yine kaybolur. Reddedildi.

## Kanıt
`docs/data-contracts.md`; `backend/app/services/ledger.py` (`ledger_status`); `backend/app/models/open_item_match.py`.
