import Link from "next/link";
import { Logo } from "@/components/ui/logo";

const FOOTER_LINKS = {
  Ürün: [
    { label: "Özellikler",      href: "/#özellikler" },
    { label: "AI Ajanlar",      href: "/#ajanlar" },
    { label: "Fiyatlandırma",   href: "/#fiyatlandırma" },
    { label: "Değişiklik Günlüğü", href: "#" },
    { label: "Yol Haritası",    href: "#" },
  ],
  Çözümler: [
    { label: "CFO Analizi",       href: "#" },
    { label: "CEO Board Deck",    href: "#" },
    { label: "Risk Yönetimi",     href: "#" },
    { label: "ERP Entegrasyonu",  href: "#" },
    { label: "Open Banking",      href: "#" },
  ],
  Kaynaklar: [
    { label: "Dokümantasyon", href: "#" },
    { label: "API Referansı", href: "#" },
    { label: "Blog",          href: "#" },
    { label: "Durum Sayfası", href: "#" },
    { label: "Destek",        href: "mailto:hello@clevelai.com" },
  ],
  Şirket: [
    { label: "Hakkımızda",   href: "#" },
    { label: "İletişim",     href: "mailto:hello@clevelai.com" },
    { label: "Gizlilik",     href: "#" },
    { label: "Kullanım Şartları", href: "#" },
    { label: "KVKK",         href: "#" },
  ],
};

const BADGES = [
  { label: "KVKK Uyumlu",     icon: "🇹🇷" },
  { label: "SOC2 Ready",       icon: "🔒" },
  { label: "SSL Şifreli",      icon: "🛡️" },
  { label: "GDPR Uyumlu",     icon: "🇪🇺" },
];

export function LandingFooter() {
  return (
    <footer className="relative border-t border-border">
      {/* Top gradient strip */}
      <div
        aria-hidden="true"
        className="absolute inset-x-0 top-0 h-px"
        style={{
          background:
            "linear-gradient(90deg, transparent 0%, oklch(0.62 0.26 262 / 0.3) 50%, transparent 100%)",
        }}
      />

      <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">

        {/* Main footer grid */}
        <div className="grid grid-cols-2 gap-8 sm:grid-cols-2 lg:grid-cols-5">

          {/* Brand column */}
          <div className="col-span-2 lg:col-span-1">
            <Logo size="sm" />
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              Türk KOBİ&apos;leri için yapay zeka destekli
              C-Suite analiz platformu.
            </p>

            {/* Trust badges */}
            <div className="mt-4 flex flex-wrap gap-2">
              {BADGES.map((b) => (
                <span
                  key={b.label}
                  className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/30 px-2.5 py-1 text-[11px] text-muted-foreground"
                >
                  <span aria-hidden="true">{b.icon}</span>
                  {b.label}
                </span>
              ))}
            </div>
          </div>

          {/* Link columns */}
          {Object.entries(FOOTER_LINKS).map(([group, links]) => (
            <div key={group}>
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-foreground/70">
                {group}
              </h3>
              <ul className="space-y-2">
                {links.map((link) => (
                  <li key={link.label}>
                    <Link
                      href={link.href}
                      className="text-sm text-muted-foreground transition-colors hover:text-foreground"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {/* Bottom bar */}
        <div className="mt-10 flex flex-col items-center justify-between gap-3 border-t border-border pt-6 sm:flex-row">
          <p className="text-sm text-muted-foreground">
            © {new Date().getFullYear()} C-Level AI. Tüm hakları saklıdır.
          </p>

          <div className="flex items-center gap-4">
            <a
              href="mailto:hello@clevelai.com"
              className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              hello@clevelai.com
            </a>
            {/* Social links */}
            <a
              href="https://twitter.com/clevelai"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Twitter / X"
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-white/8 hover:text-foreground"
            >
              <svg
                width="15"
                height="15"
                viewBox="0 0 15 15"
                fill="none"
                aria-hidden="true"
                className="h-4 w-4"
              >
                <path
                  d="M7.233 5.816L2.64 0H.5l5.6 6.478L.353 13H2.27l4.1-4.753 3.53 4.753H12L6.17 5.816h1.063zm-.563 0h1.063"
                  fill="currentColor"
                />
                <path
                  d="M11.6 0H9.49l-3.323 3.85L9.62 8.19 11.6 10.667V13h1.9L8.67 7.07 12.9 2.23V0h-1.3zm0 0"
                  fill="currentColor"
                />
              </svg>
            </a>
            <a
              href="https://linkedin.com/company/clevelai"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="LinkedIn"
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-white/8 hover:text-foreground"
            >
              <svg
                width="15"
                height="15"
                viewBox="0 0 15 15"
                fill="none"
                aria-hidden="true"
                className="h-4 w-4"
              >
                <path
                  d="M2 1a1 1 0 100 2 1 1 0 000-2zM1 4.5h2V13H1V4.5zM5 4.5h1.8v1.2h.025C7.1 5 8 4.3 9.5 4.3c2 0 2.5 1.3 2.5 3V13h-2V7.8c0-.8-.3-1.8-1.5-1.8S7 7 7 7.8V13H5V4.5z"
                  fill="currentColor"
                />
              </svg>
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}
