"""Ordinary Turkish words that are also names or parts of names ("Güneş", "Deniz", "Demir", "Yıldız").

A single word of a known name that is in this list is masked only where it reads as a name (capitalised and
not at the start of a sentence, or followed by an apostrophe suffix), so "güneş enerjisi" stays as written
while "ödemeyi Güneş'e yaptık" is masked. Words of a multi-word name are not affected: "Güneş Ticaret" as a
whole is always masked. The over- and under-masking this rule produces was measured on synthetic Turkish
financial text (tests/test_llm_egress_names.py); the numbers are in docs/kvkk/yapay-zeka-veri-akisi.md.
"""
from __future__ import annotations

_FOLD = str.maketrans({"ı": "i", "İ": "i", "I": "i", "ğ": "g", "ş": "s", "ö": "o", "ü": "u", "ç": "c", "â": "a",
                       "î": "i", "û": "u"})

# Given names and surnames that are also everyday words.
_NAME_WORDS = """
ak akın altın arı arslan aslan ateş avcı ay aydın bahar bal barış başak
bayram bilge bora bulut can ceylan cömert coşkun çakır çam çelik çiçek çınar dağ dalga demir
deniz dere derin doğa doğan doğru dost duman duru ece ekin elmas emin erdem erkek esen ezgi gök
gönül gül güler gümüş gün güneş güven güzel hayat ılgaz ırmak inci kader kahraman kalkan kaplan
kar kara karaca kartal kaya kaymak kazan keskin kılıç kırmızı kuğu kul kurt kuş kutlu lale mavi mercan
meltem mert mutlu nehir nur ok onur oya ozan öz özen özgür pamuk pınar polat rüzgar saygı sağlam savaş
sel selam serin sevgi sevinç şahin şeker şen şimşek taş tan temiz toprak tunç tutku türk uçar
umut ümit yağmur yaman yasemin yavuz yaz yeşil yiğit yıldırım yıldız zafer zengin
zümrüt menekşe kanarya lider ekol ufuk vizyon atlas yıldızlar cennet bereket kısmet huzur
"""

# Words that often stand alone in a company name and in ordinary financial text alike.
_BUSINESS_WORDS = """
ticaret sanayi gıda yapı holding enerji inşaat lojistik nakliyat nakliye tekstil market otomotiv turizm
teknoloji grup merkez global pazarlama danışmanlık mimarlık mühendislik tarım hizmet hizmetleri elektrik
elektronik plastik kağıt makine metal kimya ilaç medikal sağlık eğitim yayın yayıncılık reklam bilişim
yazılım kargo taşımacılık petrol akaryakıt mobilya ambalaj ofis kırtasiye gayrimenkul emlak sigorta
finans yatırım dış iç uluslararası anadolu marmara ege akdeniz karadeniz istanbul ankara izmir bursa
türkiye avrupa asya doğu batı kuzey güney yeni modern dijital akıllı mega süper ana birlik ortak
kooperatif vakıf dernek ajans atölye fabrika mağaza depo büro kafe restoran otel pastane fırın eczane
klinik hastane okul kurs çağrı servis bakım temizlik güvenlik danışman proje plan tasarım dekor
çözüm sistem sistemleri ürün ürünleri malzeme malzemeleri madencilik maden çimento cam seramik deri
ayakkabı giyim moda kozmetik oyuncak spor sağlıklı organik doğal tarım hayvancılık süt et tavuk balık
un şeker çay kahve su meyve sebze baharat yağ zeytin fındık pamuklu ipek halı perde boya kimyasal
""" + """
banka bankası kredi nakit kasa hesap fatura ödeme tahsilat havale çek senet borç alacak gelir gider
satış alış müşteri tedarikçi stok sipariş fiyat tutar bakiye vergi kdv maaş kira prim avans iade
"""

COMMON_WORDS: frozenset[str] = frozenset(
    w.translate(_FOLD).lower() for w in (_NAME_WORDS + _BUSINESS_WORDS).split()
)
