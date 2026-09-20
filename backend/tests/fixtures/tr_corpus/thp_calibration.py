"""Kalibrasyon seti — sınıflandırıcının isabetini *ölçmek* için, geçirmek için değil.

`thp_cases.THP_GOLDEN_CASES` is a regression gate: every case must pass, so
measuring accuracy on it would report 100% by construction. This set is the
other kind. Its cases are allowed to fail; the test counts how many land on
the right account, per evidence level, and `app/services/accounting/guven.py`
publishes those counts as the confidence a reviewer sees.

Ground truth is the Tekdüzen Hesap Planı, written before the classifier was
run on the row — never copied from its output. Three sources:

1. The golden cases (already vetted).
2. Every row of the TechNova fixtures, the corpus the live runs use.
3. Bank-statement lines as Turkish SMEs actually write them, including the
   ambiguous ones a keyword engine gets wrong. A set of easy rows would make
   the published accuracy a flattering lie.

It is small. The published numbers say "test setinde x/n" precisely so nobody
reads them as a guarantee on their own books; an organisation's own SMMM
decisions replace them once there are enough (guven.GECMIS_ESIGI).
"""
from __future__ import annotations

from tests.fixtures.tr_corpus.thp_cases import THP_GOLDEN_CASES

# (description, transaction_type, expected THP account, why)
_TECHNOVA: list[tuple[str, str, str, str]] = [
    ("Ocak Yazılım Lisans Geliri - ABC Holding", "income", "600", "lisans satışı hasılattır"),
    ("Danışmanlık Hizmet Bedeli - DEF Ltd", "income", "600", "verilen hizmet hasılattır"),
    ("Ocak Ofis Kirası - Levent İstanbul", "expense", "770", "ofis kirası genel yönetim gideri"),
    ("Ocak Elektrik Faturası - İGDAŞ", "expense", "770", "ofis enerjisi genel yönetim gideri"),
    ("Ocak İnternet - Turkcell Superonline", "expense", "770", "ofis iletişimi genel yönetim gideri"),
    ("Ocak Maaş Ödemeleri - Mühendislik Ekibi", "expense", "730", "ücret personel hesabına"),
    ("Ocak Maaş Ödemeleri - Satış Ekibi", "expense", "730", "satış ekibinin ücreti de ücrettir"),
    ("Google Ads Ocak Kampanyası", "expense", "771", "reklam pazarlama gideri"),
    ("AWS Bulut Altyapı Faturası", "expense", "770", "barındırma hizmeti gider; varlık değil"),
    ("Donanım Alımı - Sunucu Bileşenleri", "expense", "255", "bilgisayar donanımı demirbaştır"),
    ("KDV Ödemesi - Aralık Dönemi", "expense", "360", "ödenen KDV borcu"),
    ("Aylık SaaS Abonelik Gelirleri", "income", "600", "abonelik satışı hasılattır"),
    ("Şubat Küçük Satış - Tek Müşteri", "income", "600", "satış hasılatı"),
    ("Şubat Ofis Kirası - Levent İstanbul", "expense", "770", "ofis kirası"),
    ("Şubat Maaş Ödemeleri - Tüm Ekip", "expense", "730", "ücret"),
    ("Aşırı Pazarlama Harcaması - Ajans Kampanyası", "expense", "771", "ajans kampanyası pazarlama gideri"),
    ("Tekrar Eden Tedarikçi Ödemesi - XYZ Bilişim", "expense", "320", "tedarikçiye ödeme satıcı borcunu kapatır"),
]

_BANKA_EKSTRESI: list[tuple[str, str, str, str]] = [
    ("Müşteri tahsilatı - Fatura No 2024/118", "income", "120", "faturası daha önce kesilmiş alacağın tahsili"),
    ("Kira geliri - Depo", "income", "602", "esas faaliyet dışı kira geliri"),
    ("Mevduat faiz geliri", "income", "602", "faiz geliri diğer gelir"),
    ("Kredi faiz ödemesi - Yapı Kredi", "expense", "657", "kredi faizi finansman gideri"),
    ("Stopaj ödemesi muhtasar", "expense", "360", "muhtasar ile ödenen stopaj"),
    ("SGK prim ödemesi Ocak", "expense", "361", "sosyal güvenlik kesintisi"),
    ("Kırtasiye alımı", "expense", "770", "büro sarf malzemesi"),
    ("Ofis mobilya alımı", "expense", "255", "mobilya demirbaştır"),
    ("Muhasebe ücreti - SMMM Mart", "expense", "770", "muhasebe hizmeti genel yönetim gideri"),
    ("Kargo gönderim bedeli - Aras", "expense", "771", "satış dağıtım gideri"),
    ("Ticari mal alımı - Tedarikçi ABC", "expense", "153", "satılmak üzere alınan mal"),
    ("Banka kredisi kullanımı", "income", "300", "kullanılan kredi borçtur, gelir değil"),
    ("İhracat bedeli - Almanya müşteri", "income", "601", "yurt dışı satış"),
    ("Temizlik hizmeti bedeli", "expense", "770", "ofis temizliği"),
    ("Facebook reklam ödemesi", "expense", "771", "reklam"),
    ("Geçici vergi ödemesi", "expense", "193", "peşin ödenen vergi"),
    ("Araç yakıt gideri", "expense", "770", "şirket aracı yakıtı genel yönetim gideri"),
    ("Personel yemek kartı yüklemesi", "expense", "730", "personele sağlanan yan hak"),
    ("EFT - Ahmet Yılmaz serbest meslek ödemesi", "expense", "770", "dışarıdan alınan danışmanlık"),
    ("Havale gelen - Demir İnşaat", "income", "120", "müşteriden gelen ödeme alacağı kapatır"),
]

THP_CALIBRATION_CASES: list[tuple[str, str, str, str]] = [
    *THP_GOLDEN_CASES,
    *_TECHNOVA,
    *_BANKA_EKSTRESI,
]
