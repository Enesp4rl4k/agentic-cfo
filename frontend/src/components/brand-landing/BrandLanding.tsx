import Link from "next/link";
import { ThemeIconToggle } from "@/components/ui/theme-toggle";
import { GuestDemoButton } from "@/components/demo/GuestDemoButton";
import { brand } from "@/lib/branding";
import { getMessages, type AppLocale } from "@/lib/i18n";
import { Hermes, TreeOfLife, Wolf } from "./figures";
import { ProductTabs } from "./ProductTabs";
import { SailMark } from "./SailMark";
import { StormShip } from "./StormShip";
import styles from "./brand.module.css";

/**
 * Brand landing (Tunç Çağı). Design source and rules: DESIGN.md → Brand layer.
 * A server component: only the storm scene and the product tabs are client code.
 * Every visible string comes from the i18n messages (`brandLanding`), in the
 * locale the route resolved; the default is Turkish, the brand's first language.
 */

/**
 * The wordmark is a Latin proper name (Tiphys, Argo's helmsman), so it is upper-cased by the
 * Latin rule: TIPHYS, never TİPHYS. Owner's decision, 2026-11-14 (DESIGN.md → Logo).
 */
const wordmark = brand.name.toLocaleUpperCase("en-US");

export function BrandLanding({ locale = "tr" }: { locale?: AppLocale }) {
  const m = getMessages(locale).brandLanding;

  return (
    <div className={styles.root}>
      <a className={styles.skip} href="#icerik">
        {m.skip}
      </a>

      <header className={styles.wrap}>
        <nav className={styles.nav} aria-label={m.navLabel}>
          <Link href="/" className={styles.brandLink} aria-label={`${brand.name} — ${m.homeLabel}`}>
            <SailMark size={34} />
            <span className={styles.wordmark}>{wordmark}</span>
          </Link>
          <div className={styles.navLinks}>
            <a className={styles.navlink} href="#urun">{m.nav.product}</a>
            <a className={styles.navlink} href="#nasil">{m.nav.how}</a>
            <a className={styles.navlink} href="#guven">{m.nav.trust}</a>
            <a className={styles.navlink} href="#sss">{m.nav.faq}</a>
            <ThemeIconToggle className={styles.themeToggle} />
            <Link className={styles.loginLink} href="/auth/login">{m.nav.login}</Link>
          </div>
        </nav>
      </header>

      <main id="icerik">
        {/* Hero: names what is sold and for whom; the storm line is the second line. */}
        <section className={styles.wrap} aria-labelledby="hero-h1">
          <div className={styles.hero}>
            <div className={styles.heroText}>
              <span className={`${styles.eyebrow} ${styles.rise}`}>{m.hero.eyebrow}</span>
              <h1 id="hero-h1" className={`${styles.display} ${styles.h1} ${styles.rise} ${styles.d1}`}>
                {m.hero.titleBefore}
                <em>{m.hero.titleEm}</em>
                {m.hero.titleAfter}
              </h1>
              <p className={`${styles.tagline} ${styles.rise} ${styles.d1}`}>{m.hero.tagline}</p>
              <p className={`${styles.lead} ${styles.rise} ${styles.d2}`}>{m.hero.lead}</p>
              <div className={`${styles.actions} ${styles.rise} ${styles.d3}`}>
                <Link className={`${styles.btn} ${styles.lift}`} href="/auth/register">{m.hero.primary}</Link>
                <a className={`${styles.btnGhost} ${styles.lift}`} href="#urun">{m.hero.secondary}</a>
              </div>
              <ul className={`${styles.sources} ${styles.rise} ${styles.d4}`}>
                {m.hero.sources.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </div>
            <div className={`${styles.heroArt} ${styles.artIn}`}>
              <StormShip label={m.hero.sceneLabel} />
            </div>
          </div>
        </section>

        {/* Product tour. */}
        <section id="urun" className={`${styles.wrap} ${styles.section} ${styles.reveal}`} aria-labelledby="urun-h2">
          <div className={styles.sectionHead}>
            <div>
              <span className={styles.eyebrow}>{m.product.eyebrow}</span>
              <h2 id="urun-h2" className={`${styles.display} ${styles.h2}`}>{m.product.title}</h2>
            </div>
            <p className={styles.sectionLead}>{m.product.lead}</p>
          </div>
          <ProductTabs copy={m} />
        </section>

        {/* How it works: five stops, Hermes carries the idea. */}
        <section id="nasil" className={`${styles.wrap} ${styles.section} ${styles.reveal}`} aria-labelledby="nasil-h2">
          <div className={styles.sectionHead}>
            <div>
              <span className={styles.eyebrow}>{m.how.eyebrow}</span>
              <h2 id="nasil-h2" className={`${styles.display} ${styles.h2}`}>{m.how.title}</h2>
              <p className={styles.sectionLead}>{m.how.hermes}</p>
            </div>
            <Hermes className={styles.figHermes} />
          </div>
          <ol className={styles.steps}>
            {m.steps.map((s, i) => (
              <li key={s.n} className={`${styles.step} ${i === 3 ? styles.stepDark : ""}`}>
                <span className={styles.stepNum}>{s.n}</span>
                <h3 className={styles.display}>{s.title}</h3>
                <p>{s.body}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* Trust: what the visitor can check, said as a promise, never as a warning. */}
        <section id="guven" className={`${styles.wrap} ${styles.section} ${styles.reveal}`} aria-labelledby="guven-h2">
          <div className={styles.trust}>
            <div className={styles.trustHead}>
              <h2 id="guven-h2" className={`${styles.display} ${styles.trustTitle}`}>
                {m.trust.titleBefore}
                <em>{m.trust.titleEm}</em>
                {m.trust.titleAfter}
              </h2>
            </div>
            <ul className={styles.pillars}>
              {m.pillars.map((p) => (
                <li key={p.title}>
                  <h3>{p.title}</h3>
                  <p>{p.body}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* FAQ: native disclosure, works without script. */}
        <section id="sss" className={`${styles.wrap} ${styles.section} ${styles.faqSection} ${styles.reveal}`} aria-labelledby="sss-h2">
          <h2 id="sss-h2" className={`${styles.display} ${styles.h2}`}>{m.faq.title}</h2>
          <div className={styles.faq}>
            {m.faq.items.map((f) => (
              <details key={f.q}>
                <summary>{f.q}</summary>
                <p>{f.a}</p>
              </details>
            ))}
          </div>
        </section>

        <section className={`${styles.wrap} ${styles.section} ${styles.reveal}`} aria-labelledby="kapanis-h2">
          <div className={styles.closeBox}>
            <Wolf className={styles.figWolf} />
            <h2 id="kapanis-h2" className={`${styles.display} ${styles.closeTitle}`}>{m.close.title}</h2>
            <p className={styles.closeNote}>{m.close.note}</p>
            <div className={`${styles.actions} ${styles.closeActions}`}>
              <Link className={`${styles.btn} ${styles.lift}`} href="/auth/register">{m.close.cta}</Link>
              {/* The one-click guest demo keeps a door on the homepage. */}
              <GuestDemoButton className={`${styles.btnGhost} ${styles.lift}`}>{m.close.demo}</GuestDemoButton>
            </div>
          </div>
        </section>
      </main>

      <footer className={styles.footer}>
        <div className={`${styles.wrap} ${styles.footerRow}`}>
          <span className={styles.footerBrand}>
            <SailMark size={24} small />
            <span className={styles.wordmark}>{wordmark}</span>
          </span>
          <span className={styles.carpe}>
            <TreeOfLife className={styles.tree} />
            <span>
              <i>{m.footer.carpe}</i>
              <small>{m.footer.carpeSub}</small>
            </span>
          </span>
          <span className={styles.footerLinks}>
            {m.footer.sample} ·{" "}
            <Link className={styles.navlink} href="/auth/login">{m.nav.login}</Link>
          </span>
        </div>
      </footer>
    </div>
  );
}
