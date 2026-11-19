# 0007 · Mimari kurallar küçülen listelerle (ratchet) testte

- **Durum:** Kabul edildi (#54, 2026-11-14)
- **Kimin:** Geliştirici
- **Plan v11:** §8 (F1–F10), A0.8

## Bağlam
Hedef mimarinin tutup tutmadığı ancak testle bilinebilir. Bugünkü kod hedefin birçok kuralını ihlal ediyor (600 satırı geçen 17 dosya, hiçbir yerden içe aktarılmayan 20 modül). Hepsini bir PR'da düzeltmek mümkün değil, ama yenilerinin eklenmesi engellenmeli.

## Karar
Her mimari kural bir testtir ve bugünkü ihlallerin listesiyle başlar. Yeni bir ihlal testi düşürür; listede olup artık ihlal etmeyen bir kayıt da testi düşürür ve listeden silinmesini ister. Liste yalnız küçülür. Desen, içe aktarma yönü testinde (`test_architecture_boundaries.py`) zaten vardı; F2 (dosya boyu), F3 (SMTP yalnız teslim servisinde) ve F5 (çağıranı olmayan modül) aynı desenle eklendi (`test_architecture_fitness.py`).

## Sonuçlar
- Borç büyümez; her temizlik PR'ı listeyi küçültür ve test bunu ister (A0.3 ve A0.4b'de oldu).
- Liste, kalan borcun ölçüsüdür.
- Bir kuralı gevşetmek görünür bir test değişikliği gerektirir.

## Alternatifler
- **Kuralı yalnız belgeye yazmak:** uygulanmaz.
- **Önce bütün ihlalleri düzeltip sonra katı kural koymak:** aylarca sürer; bu sürede yeni ihlaller girer.

## Kanıt
`backend/tests/test_architecture_fitness.py`, `backend/tests/test_architecture_boundaries.py` (#54, #59, #61).
