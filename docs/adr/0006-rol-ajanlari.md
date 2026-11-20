# 0006 · Rol ajanları kanıt olmadan pilot yoluna dönmez

- **Durum:** Önerildi (2026-11-19); sahip kararı
- **Kimin:** Sahip
- **Plan v11:** K6, C6; A3.5

## Bağlam
CFO dışında yedi rol var (CEO, CTO, CMO, COO, CHRO, Risk/Denetim/Uyum). Odak modu (v10 O0) bunları pilot şirketin menüsünden gizliyor. Rol ajanları finans defterinden beslenmiyor ve güvenlerini ölçmüyor (G13); bazıları `auto_chain` ile CFO koşusundan sonra tetikleniyor ve LLM maliyeti doğuruyor.

## Karar
Bir pilot şirket istemedikçe rol ajanları `auto_chain`'den çıkarılır ve menüye dönmez; kod silinmez. Bir rol ancak (1) bir pilot onu istediğinde, (2) defterden beslendiğinde ve (3) güvenini ölçüp güven kapısından geçtiğinde yeniden açılır.

## Sonuçlar
- Pilot yolunda gereksiz LLM maliyeti ve bakım yükü azalır.
- Rol verisi bağlayıcıları (Stripe, CRM, İK dışa aktarımları) bu karara bağlıdır (`docs/connectors.md`).
- Rollerin ürün anlatısındaki genişliği şimdilik ekranda görünmez.

## Alternatifler
- **Rolleri olduğu gibi bırakmak:** kanıtsız genişlik (plan v10 §2). Reddedildi.
- **Rolleri silmek:** geri dönüşü pahalı; bir pilot isterse gerekebilir. Reddedildi.

## Kanıt
`backend/app/agents/orchestration/auto_chain.py`; `frontend/src/lib/nav-focus.ts`; PLAN_V10 §14 G13.
