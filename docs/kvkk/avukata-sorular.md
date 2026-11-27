# Avukata sorular (tek liste)

> Bu mühendislik çalışması hukuki görüş değildir. Aşağıdaki her soru için kodda **muhafazakâr bir varsayılan**
> seçildi; hukukçu farklı bir cevap verirse değişen şey bir ayardır, mimari değil. PR #68'deki
> [acik-konular.md](acik-konular.md) sahibin karar listesidir; bu liste onu tamamlar ve veri yaşam döngüsü
> işlerinin (silme, dışa aktarma, saklama, bildirim) ürettiği soruları toplar. Haritanın kendisi:
> [veri-envanteri-uretilen.md](veri-envanteri-uretilen.md).

| # | Soru | Seçilen muhafazakâr varsayılan | Nerede ayarlanır |
|---|---|---|---|
| Q1 | LLM sağlayıcısına (varsayılan DeepSeek), SMTP'ye (varsayılan Gmail), Stripe'a ve açılırsa Sentry'ye giden veri için yurt dışına aktarım dayanağı (KVKK m.9) nedir? Maskeleme zorunlu mu? Master'da maskeleme yoktu; bu çalışmayla üç kip var (`off` / `masked` / `raw`) ve varsayılan **`masked`** önerilir: kimlik kalıpları ve defterin bildiği adlar yer tutucuyla gider, **serbest metin kalabilir** (ayrıntı, seçenekler ve kalan risk: Q15 ve [yapay-zeka-veri-akisi.md](yapay-zeka-veri-akisi.md)). | Sağlayıcı ayarı değişmedi. Pilot, LLM anahtarı **tanımsız** ya da `LLM_DATA_MODE=off` ile (çağrı yok, şablon metin) açılabilir; harita ve ayarlar ekranı neyin gittiğini ve hangi kipte olduğunu gösterir. | `LLM_*`, `SMTP_*`; [THIRD_PARTIES](../../backend/app/services/privacy/registry.py) |
| Q2 | Muhasebe kayıtları (işlem, defter, açık kalem, SMMM onayı) için Platform'un saklama yükümlülüğü: VUK 253 (5 yıl) mı, TTK 82 (10 yıl) mu, yoksa asıl defter şirkette ve SMMM'de olduğu için Platform kopyası için kısa süre mi? Süre sonunda silme mi anonimleştirme mi? | **Hiçbir şey otomatik silinmez.** Silme isteğinde kayıtlar tutulur, kişisel sütunlar silinir (anonimleştirme). | `RETAINED` (org_erasure.py); saklama işi defter tablolarına dokunmaz |
| Q3 | Bir şirket her şeyin silinmesini isterse defter kayıtları da silinebilir mi (`hard_delete`)? | Kapalı (`ORG_ERASURE_HARD_DELETE_ENABLED=false`). | aynı ad |
| Q4 | Üye silme: kişi silinirken "kim karar verdi" kaydı tutulabilir mi? Kararı, sabit bir takma ad (`member-<12 hex>`) ile ilişkilendirmek yeterli mi? `decisions.reason` (kişinin yazdığı serbest metin) tutulabilir mi? | Takma adlı tutma; e-posta, ad, parola, IP, tarayıcı, üyelik silinir; karar kaydı ve `reason` **tutulur** (denetim izi bütün kalır). | `member_erasure.py` |
| Q5 | Denetim kaydı ve erişim kayıtlarında IP/tarayıcı bilgisini ne kadar tutmak meşru? Kaydın kendisi ne kadar? | IP son bölümü kısaltılır, 365 gün sonra; tarayıcı bilgisi 365 gün sonra silinir; kaydın kendisi silinmez.  | `RETENTION_AUDIT_IP_DAYS` |
| Q6 | Yüklenen ham dosyalar ve `raw_text`: işlendikten sonra ne kadar? | **Süresiz tut** (0 = kapalı); sahip ve hukukçu bir gün sayısı verirse açılır. | `RETENTION_UPLOAD_DAYS` |
| Q7 | Teslim edilmiş giden e-posta gövdeleri (karşı taraf adı içerebilir) ne kadar? | Teslimden 90 gün sonra gövde silinir, üst veri (alıcı, durum, zaman) kalır. | `RETENTION_OUTBOX_BODY_DAYS` |
| Q8 | Süresi dolan jeton, davet, bildirim, uyarı geçmişi, iş kayıtları için süreler. | Jeton/davet: süre sonu + 30 gün. Bildirim: 180 gün. Uyarı geçmişi ve iş günlükleri: 365 gün. | `RETENTION_*` |
| Q9 | Karşı taraf (faturadaki gerçek kişi) m.11 ile "bende ne var, sil" derse: veri sorumlusu şirket midir, Platform veri işleyen midir; Platform kişi adıyla arama/silme sunmalı mı? | Sunulmuyor. Şirket sahibi dışa aktarım ve silme araçlarını kullanır; kişi adıyla arama yok. | — |
| Q10 | İhlal bildirimi: Platform ihlalinde Kurul'a 72 saat içinde kim, hangi sırayla bildirir (veri sorumlusu şirketler mi, Platform mu)? Ürünün ihlal kaydı şirket başınadır. | Runbook: operatör etkilenen şirketleri "gecikmeksizin" bilgilendirir; kapsam kayıt defterinden hesaplanır. | [data-breach.md](../ops/runbooks/data-breach.md) |
| Q11 | Silme için bekleme (soğuma) süresi: 7 gün makul mü? Kişi isteği için 30 gün yanıt süresiyle uyumlu mu? | 7 gün, iptal edilebilir; 0 yapılırsa hemen. Operatör kaynaklı silme en az 1 gün bekler. | `ERASURE_COOLING_OFF_DAYS` |
| Q12 | Yedeklerdeki veri: silinen verinin yedek dönüşüne (14 gün) kadar yedekte kalması kabul mü? Geri yükleme sonrası silmeyi yeniden uygulamak yeterli mi? | Evet varsayıldı; ifade [yedek-ve-silme.md](yedek-ve-silme.md). | `scripts/reapply_erasures.py` |
| Q13 | Aydınlatma metni ve kullanım koşulları sürümleri: yeni sürümde kullanıcıdan yeniden onay mı, yalnız bildirim mi? | Yeniden onay istenir (sürüm değişince). Metinleri PR #68'in belgeleri sağlar. Bugünkü durum: girişten sonra (ve açık oturumla uygulama yüklenince), sunucu bu kişi için güncel sürümlerden biri kabul edilmemiş diyorsa uygulama yerine bir istem gösterilir (başlık, sürüm, metnin bağlantısı, açık "Okudum, kabul ediyorum" düğmesi; önceden işaretli kutu yok, kapatarak kabul yok; çıkış yapılabilir). Kabul kanıtı yalnızca sunucunun o an yayımladığı sürüm için yazılır (`POST /privacy/notices/accept`; eski, gelecek veya bilinmeyen sürüm reddedilir). Kayıt ve davet-kabul sayfaları bugün metni göstermediği için sürüm göndermez; kişi ilk girişte istemle karşılaşır. **Sorular:** istem yalnızca ön yüzde uygulanır (API çağrıları kabul olmadan da çalışır; [muhendislik-notlari.md](muhendislik-notlari.md)): bu pilot için yeterli mi? Üretimde metin bağlantıları (`PRIVACY_NOTICE_URL`, `TERMS_URL`) tanımsızsa sunucu başlamaz (preflight); geliştirme ortamında tanımsızsa istem bunu açıkça söyler. Kayıt sayfasında da metin gösterilip ayrıca, işaretlenmemiş bir kutuyla onay alınmalı mı? | `PRIVACY_NOTICE_VERSION`, `TERMS_VERSION` |
| Q14 | Üçüncü taraf sağlayıcılar (Stripe, OAuth sağlayıcıları, ERP) silmeden sonra hâlâ kopya tutuyor: Platform bu kopyaları kapatmakla mı yükümlü? | Silme kaydı operatöre hangi kopyaların kaldığını **sayıyla** söyler (Stripe müşterisi, ERP/bağlayıcı sayısı); operatör runbook adımlarını izler. | `counts._external_followup` |
| Q15 | LLM sağlayıcısına (Q1) giden veri için hangi mühendislik yolu seçilmeli: (a) sağlayıcı ve bölge seçimi, (b) göndermeden önce ad ve kimlik bilgilerinin maskelenmesi, (c) şirket başına açma/kapama (opt-in), (d) aydınlatma metninde açıklama, (e) yalnızca gömme (embedding) çağrısını kapatma? Şirket adı, karşı taraf adı ve işlem açıklamaları hangi kişisel veri kategorisine girer; vergi no ya da IBAN metin içinde geçerse ne olur? Sağlayıcı sözleşmeyle veriyi saklamıyor ve eğitimde kullanmıyorsa bu, aktarım dayanağını değiştirir mi? | Sağlayıcı değişmedi: varsayılan uç `https://api.deepseek.com`, model `deepseek-chat`. Artık kip vardır: sunucu `LLM_DATA_MODE` (önerilen varsayılan `masked`) ve şirket sahibinin kendi seçimi (yalnızca sıkılaştırır; karar kaydı tutulur). Anahtar tanımsız ya da `llm-placeholder-*` ise ağ çağrısı yapılmaz. Taban durumu ve bu değişiklikle mümkün olanlar aşağıda. | `OPENAI_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_DATA_MODE`, `LLM_DOCUMENT_TEXT`, `LLM_ORG_MAY_RELAX`, `RAG_EMBEDDING_ENABLED` |


## Q15: bu değişiklikle teknik olarak mümkün olanlar (seçenek, sonuç değil)

Aşağıdakiler **seçeneklerdir**; hangisinin yeterli olduğu hukukçunun ve sahibin kararıdır. Neyin gittiğinin tam tablosu ve kalan risk:
[yapay-zeka-veri-akisi.md](yapay-zeka-veri-akisi.md).

- **Tek geçit ve kanıtı.** Model ve gömme çağrılarının hepsi iki dosyadan geçer; başka kod istemci kuramaz (AST testi). 49 çağrı yeri, sağlayıcının
  aldığını kaydeden sahte bir sağlayıcıyla çalıştırılır; maskeli kipte kanarya değerlerin hiçbiri hiçbir yükte yoktur.
- **(b) Maskeleme artık vardır.** `LLM_DATA_MODE=masked`: IBAN (mod 97), TCKN, VKN, kart (Luhn), telefon, e-posta, plaka **açık kanıtla** (etiket ya da
  şaşmaz biçim) ve defterin kendi tablolarından bilinen adlar (şirket, karşı taraf, tedarikçi, üye, mali müşavir; ekli, satır bölünmüş, yalnızca ad ya da
  soyad yazımları dahil) yer tutucuyla gider, yanıtta baytı baytına geri çevrilir. Tutar, tarih ve para birimi **değişmez** (200.000+ satırlık
  bulanık testte sıfır değişiklik). **Bedeli:** adın anlamına dayanan çıkarımlarda kalite biraz değişebilir. **Sınırı:** serbest metinde kalıpların ve
  defterin bilmediği kişisel veri gidebilir: özellikle **okunan belgede ilk kez geçen, henüz defterde olmayan adlar olduğu gibi gider**; etiketsiz
  VKN/kart numarası ve `+90`/boşluksuz cep numarası, tutarlarla karışmasın diye bilinçli olarak kalıpla maskelenmez (etiketsiz TCKN, tutar değilse maskelenir). Bu, tam güvence değildir.
- **Kapalı kalarak başarısız olma.** Maskeli kipte bir çağrının şirketi bilinmiyorsa ya da şirketin isim listesi okunamazsa o çağrı **yapılmaz**
  (adlar maskesiz gitmez); ret kaydedilir, sahibin ekranında ve işletmeciye uyarıda görünür. Şirketsiz çalışmasına izin verilen sistem işi listesi bugün boştur.
- **İzleme (LangSmith).** Varsayılan kapalı; açılırsa bile girdi ve çıktılar gizlenir (yük gitmez), üretimde başlangıç denetimi uyarır.
- **(c) Şirket başına seçim artık vardır.** Sahip, Ayarlar > Veri ve gizlilik'ten `off`, `masked` veya (işletmeci izin verirse) `raw` seçer; her seçim kim/ne zaman
  ile karar kaydına yazılır. `off` kipinde hiçbir çağrı yapılmaz; ürün rakamlar ve kural tabanlı metinlerle çalışır, sohbet ve yazılı özetler kapalıdır.
- **Belge metni için sıkı kip.** `LLM_DOCUMENT_TEXT=never`: hiçbir kipte belge metni gitmez; belge okuma deterministik ayrıştırıcılara kalır ve yükleme sonucu yapay zekâ adımının
  atlandığını söyler. Ayrıştırıcının tanımadığı belgeler bu durumda incelemeye düşer.
- **(e) Gömme.** Maskeli kipte gömme, kararlı (şirkete özel, sırla anahtarlanmış) takma adlarla hesaplanır, indeks ve sorgu aynı belirteci kullanır; `off` kipinde
  gömme yoktur (TF-IDF). `RAG_EMBEDDING_ENABLED=false` hâlâ ayrı bir anahtardır.
- **Denetim.** Her çağrı için kip, değiştirilen yer tutucu sayıları ve gönderilen bayt kaydedilir (yük yok); sahibin ekranı son 30 günün çağrı ve bayt sayısını gösterir.
- **Hâlâ açık sorular (bu çalışma karar vermez):** `masked` yeterli bir önlem mi, yoksa belge metni (`never`) veya `off` mi gerekir? Yer tutucuyla gönderilen
  tutar, tarih ve defter yapısı hangi kategoriye girer? Kararlı gömme belirteçleri (tekrar bilgisi) kabul edilebilir mi? Sağlayıcı değişirse (a) kodsuz bir ayardır.

## Q15 için mühendislik gerçekleri (master'da koddan doğrulandı, 2026-11-23; bu değişikliğin TABANI, bugünkü durum için yukarıya bakın)

Bunlar hukuki sonuç değil, kodun bugün yaptığı şeydir; her biri aşağıdaki dipnotta dosya:satır ile gösterilir.

- **Uç ve model.** Varsayılan `LLM_BASE_URL` `https://api.deepseek.com`, varsayılan `LLM_MODEL` `deepseek-chat`; uç, OpenAI uyumlu herhangi bir adresle değiştirilebilir [1]. Anahtarın ortam değişkeni adı `OPENAI_API_KEY`dir; sohbet çağrıları ve gömme çağrıları aynı anahtarı ve aynı uç adresini kullanır [1][2].
- **Anahtar yokken.** Anahtar tanımsız ya da `llm-placeholder-` ile başlıyorsa çağrı yapılmaz, model gerektiren yerler şablon metne düşer [2]. Şirket başına açma/kapama yoktur; ayarlar sunucu geneline aittir [1].
- **Maskeleme.** LLM yolunda (model ağ geçidi, belge ayrıştırma, sohbet, doğal dil sorgu, RAG) ad, kimlik numarası ya da IBAN'ı maskeleyen veya takma adlaştıran bir adım **yoktur** [3].
- **Hangi metin gider.**
  - *Belge metni (yalnızca yedek yol):* hiçbir banka/CSV ayrıştırıcısı belgeyi tanımazsa belge metninin **ilk 8.000 karakteri** çıkarım çağrısına gider. Bu sınır kodda sabittir, bir ayar değildir. İstemde `vendor` (tedarikçi veya müşteri adı) ve `description` alanları istenir [4].
  - *Gömme parçaları:* anahtar tanımlıysa ve `RAG_EMBEDDING_ENABLED` açıksa (varsayılan açık), indekslenen belge metni **1.800 karakterlik parçalar** (200 karakter örtüşme) hâlinde gömme çağrısına gider; bu yolda 8.000 karakterlik bir üst sınır yoktur, parçalama metnin tamamı üzerinden yapılır [2][5]. Çağrı başarısız olursa yalnızca TF-IDF kullanılır [5].
  - *Sohbet:* kullanıcının sorusu ve konuşma geçmişi olduğu gibi gider; sistem isteminde özet rakamlar (gelir, kâr, nakit akışı, tahmin), en fazla 5 anomali başlığı ve **son 30 işlemin** tarih, tür, kategori, tutar ve açıklamasının ilk 40 karakteri bulunur [6][7].
  - *Anomali ve SWOT özetleri:* anomali başlıkları ve açıklamaları (tekrarlı ödemede tedarikçi adı geçer) ve SWOT isteminde şirket adı gider [8][9].
  - Bu liste her çağrı yerini saymaz: `complete_text` / `stream` 32 dosyada kullanılıyor ve her biri tek tek gözden geçirilmedi. Tam liste için PR #68 bölüm 4 ve [THIRD_PARTIES](../../backend/app/services/privacy/registry.py).
- **Seçenekler (mühendislik açısından; hukuki öneri değildir).**
  - (a) Sağlayıcı/bölge: uç adresi ve model bir ayardır, kod değişmez; sağlayıcı seçimi ve sözleşmesi sahibin ve hukukçunun kararıdır.
  - (b) Maskeleme: model ağ geçidinin önünde, göndermeden önce tedarikçi/müşteri adı, vergi no, IBAN ve e-posta kalıplarını belirteçle değiştirip yanıtta geri koyan bir katman yazılabilir. Bedeli: adın modele görünmediği yerlerde çıkarım ve sohbet kalitesi düşer; serbest metinde kalıp kaçırma olasılığı vardır (kalıp tabanlı maskeleme tam güvence vermez).
  - (c) Şirket başına opt-in: bir şirket ayarı ve her çağrı yerinde denetim gerekir; kapalıyken ilgili özellikler şablon metne düşer.
  - (d) Aydınlatma metni: metni sahip/hukukçu yazar; ürün yalnızca sürümü ve kabul kanıtını tutar. "Veri ve gizlilik" ekranı bugün sağlayıcıyı ve verinin maskelenmediğini açıkça gösterir.
  - (e) `RAG_EMBEDDING_ENABLED=false`: belgenin tamamının gömme çağrısıyla gitmesini keser; belge arama TF-IDF ile sürer, sohbet ve çıkarım çağrıları etkilenmez.

### Dipnotlar (dosya:satır; bu değişikliğin tabanındaki master)

1. `backend/app/config.py:61` (`openai_api_key`), `:301` (`llm_model`), `:314` (`llm_base_url`). `backend/app/models/organization.py` içinde LLM ya da OpenAI ile ilgili bir alan yok (arandı, eşleşme yok).
2. `backend/app/platform/model_gateway.py:87-90` (`is_placeholder_key`), `:271-272` (yer tutucu anahtarda `LLMUnavailable`), `:281` (`base_url`). `backend/app/services/rag_service.py:121-128` (gömme desteği anahtar ve `rag_embedding_enabled` ister), `:131-144` (aynı `llm_base_url` ve anahtarla `embed_documents`).
3. Aranan kalıplar `mask`, `redact`, `anonymi`, `pseudonym` (büyük/küçük harf fark etmez); `backend/app/platform/`, `backend/app/agents/data_ingestion.py`, `backend/app/agents/chat_agent.py`, `backend/app/agents/nl_query_engine.py`, `backend/app/services/rag_service.py` altında eşleşme yok.
4. `backend/app/agents/data_ingestion.py:90-119` (`_extract_transactions_with_llm`, istem `raw_text[:8000]` `:119`), `:529-531` (yalnızca banka/CSV ayrıştırıcıları eşleşmezse çağrılır).
5. `backend/app/services/rag_service.py:89-92` (`_chunk_text`, `max_chars=1800`, `overlap_chars=200`), `:145-147` (hata olursa TF-IDF), `:176` (`_embed_texts(chunks)`); parçalar `rag_chunks` tablosuna yazılır (`backend/app/models/rag_chunk.py:33`).
6. `backend/app/agents/chat_agent.py:40-120` (`_build_financial_context`; `max_transactions=30` `:43`, açıklama `[:40]` `:118`, anomali başlıkları `[:5]`).
7. `backend/app/platform/model_gateway.py:285-297` (`_build_messages`: sistem istemi, konuşma geçmişi, soru).
8. `backend/app/agents/anomaly_agent.py:109-135` (başlık ve açıklamada tedarikçi adı, `:121`), `:426-438` (özet `complete_text` istemi).
9. `backend/app/agents/ceo/swot_agent.py:342-375` (`company_name` isteme girer).
