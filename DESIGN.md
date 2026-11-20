# Tiphys interface direction: Tunç Çağı

> One system, for the whole product: the marketing site, the weekly report PDF, the seal, mobile
> notification surfaces, the logo and the in-app screens. The earlier in-app direction ("Karar
> Atlası": warm ink, brass, Inter, cartographic accents) has been retired. Its tokens, shell, logo
> and login illustration are gone; the old accent names (`brass`, `copper`, `clay`, `sage`,
> `mapblue`, `parchment`) survive only as aliases of the brand's scales so no page broke.
> Design source: the "Tunç Çağı Marka Tasarımı" canvas (Logo v4, Palet, Tipografi, Figürler v2,
> Grafik seti, Landing, operasyon sayfaları).

## Brand — Tunç Çağı

### Idea
A Bronze-Age Aegean voyage, told as cash flow: **the route is the 13-week cash curve, the storm is
the week cash goes negative, the sail is the answer you get every Monday.** Everything visual
serves that one sentence. A metaphor never replaces the plain claim (see Copy).

### Colour (60 / 30 / 10)
| Token | Hex | Use |
|---|---|---|
| `cream` | `#F2EBDD` (2nd `#E8DFCC`, paper `#FBF7EE`) | 60 % ground |
| `ink` | `#1A1A1F` (2nd `#2A2A31`, 3rd `#33333B`) | 30 % panels, text |
| `ember` | `#C2561C` marks · `#A3440F` text/buttons on cream | 10 % accent, one per view |
| dark-mode ember | `#D9652A` marks · `#E0733A` text on ink | |
| `muted` | `#5C574E` on cream · `#A9A396` on ink | secondary text |
| `ok` / `warn` / `bad` | `#2A6E42` / `#855800` / `#9E1F2E` | status only, outside the 10 % |

Contrast is checked, not assumed: ink on cream 14.6:1, `#A3440F` on cream 5.2:1, `#E0733A` on ink
5.5:1, status colours ≥ 5.2:1. Red appears only for a negative balance. No violet, no gradients
on text, no neon.

### Type
- **Cinzel** — wordmark (`İSİM`, letter-spacing .14em) and small uppercase eyebrows (.16em). Caps only.
- **Cormorant Garamond 600** — headlines; italic for the one emphasised word.
- **IBM Plex Sans** — body; **IBM Plex Mono** — every amount, tabular.
- Turkish rules: pages carry `lang="tr"` so `i` uppercases to `İ`; thousands `.`, decimals `,`;
  real minus `−`; `₺` before the amount, no space: `−₺184.200`.

### Logo (v4, final)
- Yard and mast draw a **T**, the initial of the working name Tiphys (Argo's helmsman). The T
  is legible but never in front of the sail: the mast stays behind an **opaque** sail. Shade
  follows the wind: a crescent on the bellied leech and a thin band under the yard; never a
  see-through sail or a mast showing through it. Mast 11 units, yard about 10 at the middle tapering to the ends.
- Wordmark: **TIPHYS**, dotless. The name is Greek, so the Latin upper case applies, not the
  Turkish İ rule. Cinzel 700, tracking .14em.
- A square sail on a mast, **asymmetric**: straight luff, leech bellied by wind from the left;
  a pennant at the masthead points the same way.
- The sail's foot is the cash curve: it dips and recovers. **No dot**, no hull, no waves under it
  (a full side-view hull reads as another firm's logo).
- **Small cut below 32 px**: mast and yard about 20 units so the T reads first at 16 px; no
  pennant, no sail shading. Favicon:
  `frontend/src/app/icon.svg`.
- Don't: symmetric sail, round heavy yard caps, a dot or drip below the sail, a mast drawn over the
  sail, recolouring the sail anything but ember.

### Figures (illustration)
Black-figure vase technique: one-colour silhouette, details *incised* in the ground colour, exactly
one ember detail. Aegean (on a plinth): Athena, Hermes, Poseidon, Truva atı (never where trust is promised: the
horse is a story of deception). Turkish (no plinth):
Bozkurt, Hüma, Tulpar, Hayat ağacı. One figure per section, always background-faint, never on
operational screens (Rota, Onay, Belgeler…) except waiting and "ready" moments. Slow motion
(3–5 s loops), all of it off under `prefers-reduced-motion`.

### Motion
Hero enters once on load; sections reveal at most once; hover lifts 2 px, press scales .98;
one live scene per page (the storm ship). Nothing moves because the page scrolled except a
section's own moment.

### Copy
- The first screen names **what is sold** and where the figures come from ("Şirketlerin nakit rotası,
  kendi belgelerinden çizilir · her pazartesi 08.00"); the storm line is the second line, not the h1.
  Never name the doubt in a headline ("uydurulmuş rakam", a Trojan horse) and never promise a fixed
  horizon in the h1: "13 haftalık" is a product fact for the app's route screen, not a limit of the
  promise.
- Buttons are a verb and an object ("Kasamı göster"). Headings carry a noun.
- **No caption under a visual.** "Rakamlar örnektir" goes in the footer line.
- **Never an invented number, price, customer or quote.** Sample figures stay internally consistent
  (13-week sample: opening ₺612.400, low −₺184.200 in week 6) and are marked as samples once.
- Mottos: *Observe · Orient · Decide · Act* as the navigation strip at the foot of operational
  pages (Belgeler → Rota → Onay/Takvim → Raporlar); *Carpe diem* at the foot of the Monday screen
  and the landing.

### Layout
One idea per screen; equal left and right edges on a 1280 px wrap with 24 px gutters; 44 px
minimum tap targets; a visible skip link; tabs with `aria-controls` and arrow keys.

## Product expression

The interface is a decision workspace for distinct management roles, not one universal dashboard. Keep a shared visual language and shell; specialize each role's information order, terminology, key comparisons, and next actions. The recurring product pattern is **status → insight → evidence/source → next action**.

## Visual system

- **Tokens:** `globals.css` holds one set, light in `:root` and warm ink in `.dark`. Every screen
  reads the shadcn token names (`bg-card`, `text-muted-foreground`, `border-border`, `bg-primary`…);
  none of them carries a fixed colour. Light is the cream page; dark is the ink of the Dashboard
  artboard (#1a1a1f page, #24242a panels, #34343b lines).
- **Ember is the one accent** (`--primary`, burnt orange): actions, focus, the selected week. It
  never implies financial gain. Green, amber and red keep their financial meaning only.
- **Status hues written into pages** (`text-emerald-400`, `bg-red-950`…) are variable scales in
  `tailwind.config.js`: dark mode keeps Tailwind's values, light mode swaps the pale text steps and
  the dark tints and darkens the middle steps, so one class reads on both grounds.
- **Opacity on tokens** (`bg-primary/5`) works through `color-mix`; before this it silently produced
  no CSS at all.
- **The shell is ink in both themes:** the sidebar is a `.dark` scope, so everything inside takes
  the dark tokens. The active item is a filled cream pill; group headings are Cinzel capitals.
- **Type:** Cormorant Garamond for titles (every `h1`, and `.tc-display`), Cinzel capitals for
  eyebrows (`.tc-eyebrow`), IBM Plex Sans for text, IBM Plex Mono for figures (`.tc-mono`). The
  faces load once in the root layout from `lib/brand-fonts.ts`; Turkish needs `latin-ext`.
- **Charts:** series and axes use the tokens or `rgb(var(--c-blue-500))`; categorical series may
  keep their own hues. Direct labels, units and a table alternative where appropriate. The cash
  curve has the zero line and its negative zone tinted.
- **Numbers:** money is formatted with the organisation's base currency and locale
  (`useCurrencyFormat`), never a hardcoded symbol; chart ticks follow the same locale; a negative
  uses a real minus.
- **Geometry:** compact rounded surfaces, thin borders, restrained elevation. No nested cards, no
  decorative blur, no gradient text, no animation without task value.
- **Interaction:** visible focus, semantic controls, keyboard access, 44 px targets, responsive
  layouts and reduced-motion support are baseline. Contrast: 4.5:1 for text, 3:1 for large text, in
  both themes (a browser scan of the key screens is how it is checked).
- **Locale:** localized copy paints in the org's language on first render; while org settings load,
  fall back from the last resolved locale to the browser language.
- **Theme:** the saved choice wins, otherwise the system's. A script in the root layout sets the
  `dark` class before first paint so nobody sees a flash.

## Shared components

- Application shell: the sail mark and TIPHYS wordmark (`components/ui/logo.tsx`), the weekly loop first (Belgeler, Nakit rotası, Onay bekleyenler, Raporlar, Ayarlar), then the grouped navigation, current page context, command search, status, notifications, theme toggle and account controls.
- Financial metric: label, value, unit/period, optional comparison or source; positive/negative color only when the data defines that meaning.
- Evidence and provenance: distinguish real, estimated, and benchmark data close to the metric or conclusion; make the explanation reachable.
- Insight/alert: explain what changed, why it matters, and a relevant action without overstating confidence.
- Every data-heavy component needs loading, empty, error, and narrow-screen behavior.

## Role-specific hierarchy

- **CFO:** profitability and cash position first; then variance, forecast, anomalies, evidence, and report/detail actions.
- **CEO:** strategic priorities, key trade-offs, cross-functional risk, and decisions needing attention.
- **CTO / CMO / CHRO / COO:** each prioritizes its own operating outcomes and data coverage. Estimated values must remain visibly distinct from connected-source measurements.
- **Risk, audit, compliance, and accounting:** emphasize exposure, traceability, ownership, review state, and the next required control action.

## Current implementation boundary

**Done.** Global tokens and fonts; the shell (ink sidebar, top bar, logo, favicon); sign-in and
sign-up (storm scene panel: no invented quote and no compliance badge, claims the product has not
earned); Nakit Radarı and Belgeler rebuilt to the artboards (the curve is drawn from the real radar
weeks, the chosen week lists API items, "Son yüklemeler" lists the jobs list as it is); the weekly
loop strip (`OodaFooter`) closes operational pages; the chart pages read the tokens. The old
landing components and the login atlas were deleted.

**Also done.** Onay, Raporlar and Ayarlar share the page head (`PageHead`: the loop step as the
eyebrow, Cormorant title) and Onay and Raporlar close with the loop strip. The product name defaults
to Tiphys in the frontend; the tagline and metadata say what the product does.

**Still to do.**
- The artboards' deeper layouts for Onay (match cards with the two candidate invoices side by side),
  Raporlar (sealed PDF preview and archive) and Ayarlar; they wear the brand but keep their old
  composition. The Monday answer screen and a payment calendar (a new feature with its own backend,
  not a restyle).
- The backend default `brand_name` is still "C-Suite" (`backend/app/config.py`): it prints in PDFs and
  in the e-Defter software name sent to GİB, so changing it is an owner decision with its tests.
- Role pages keep their own decision priorities: restyle them in focused passes, not as CFO copies.
