import Link from "next/link";
import { Logo } from "@/components/ui/logo";
import {
  TrendingUp, Shield, Zap, BarChart2, Brain, Users,
  ChevronRight, Check, ArrowRight,
  DollarSign, Activity, FileText, AlertTriangle, Target, Globe,
} from "lucide-react";

// ── Navbar ────────────────────────────────────────────────────────────────────

function Navbar() {
  return (
    <header className="fixed top-0 z-50 w-full border-b border-white/8 bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <Logo size="md" />

        <nav className="hidden items-center gap-6 md:flex" aria-label="Main navigation">
          {["Özellikler", "Ajanlar", "Fiyatlandırma", "Hakkında"].map((item) => (
            <a
              key={item}
              href={`#${item.toLowerCase()}`}
              className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              {item}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-3">
          <Link
            href="/auth/login"
            className="hidden text-sm text-muted-foreground transition-colors hover:text-foreground sm:block"
          >
            Giriş Yap
          </Link>
          <Link
            href="/auth/register"
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
          >
            Ücretsiz Başla
          </Link>
        </div>
      </div>
    </header>
  );
}

// ── Hero ──────────────────────────────────────────────────────────────────────

function Hero() {
  return (
    <section className="relative overflow-hidden pb-24 pt-32">
      {/* Background glow */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-0 -translate-x-1/2"
        style={{
          width: "900px",
          height: "600px",
          background:
            "radial-gradient(ellipse at center top, oklch(0.62 0.26 262 / 0.18) 0%, transparent 70%)",
        }}
      />

      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        {/* Badge */}
        <div className="mb-6 flex justify-center">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/8 px-3 py-1 text-xs font-medium text-primary">
            <Zap className="h-3 w-3" aria-hidden="true" />
            Yapay Zeka Destekli C-Suite Analiz Platformu
          </span>
        </div>

        {/* Headline */}
        <h1 className="mx-auto max-w-4xl text-center text-4xl font-bold tracking-tight sm:text-5xl lg:text-6xl">
          Tüm C-Suite{" "}
          <span
            style={{
              background: "linear-gradient(135deg, oklch(0.75 0.26 262), oklch(0.65 0.22 220))",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
            }}
          >
            yapay zeka ile
          </span>{" "}
          güçlendirildi
        </h1>

        {/* Subheading */}
        <p className="mx-auto mt-6 max-w-2xl text-center text-lg leading-relaxed text-muted-foreground">
          CFO, CEO, CTO, COO, CMO, CHRO — her yönetici rolü için gerçek zamanlı
          yapay zeka analizi. Muhasebe verinizi yükleyin, 5 dakikada kurumsal
          düzeyde içgörüler alın.
        </p>

        {/* CTA buttons */}
        <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
          <Link
            href="/auth/register"
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90"
          >
            Ücretsiz Deneyin
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
          <Link
            href="/auth/login"
            className="inline-flex items-center gap-2 rounded-lg border border-border px-6 py-3 text-sm font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
          >
            Demo İzle
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </div>

        {/* Trust indicators */}
        <p className="mt-4 text-center text-xs text-muted-foreground">
          Kredi kartı gerekmez · 14 gün ücretsiz · Kurulum yok
        </p>

        {/* Dashboard mockup */}
        <div className="relative mx-auto mt-16 max-w-5xl">
          <div
            className="overflow-hidden rounded-2xl border border-white/10 shadow-2xl"
            style={{
              background: "oklch(0.15 0.026 262)",
              boxShadow: "0 0 80px oklch(0.62 0.26 262 / 0.15), 0 40px 60px rgba(0,0,0,0.4)",
            }}
          >
            {/* Mock browser chrome */}
            <div className="flex items-center gap-2 border-b border-white/8 px-4 py-3">
              <div className="flex gap-1.5">
                <div className="h-3 w-3 rounded-full bg-red-500/60" />
                <div className="h-3 w-3 rounded-full bg-yellow-500/60" />
                <div className="h-3 w-3 rounded-full bg-green-500/60" />
              </div>
              <div className="mx-auto rounded-md border border-white/10 bg-white/5 px-4 py-1 text-xs text-muted-foreground">
                app.clevelai.com/dashboard
              </div>
            </div>

            {/* Mock dashboard content */}
            <div className="grid grid-cols-4 gap-3 p-4">
              {[
                { label: "Gelir", value: "₺4.8M",  color: "text-emerald-400" },
                { label: "Net Kâr", value: "₺892K", color: "text-emerald-400" },
                { label: "Nakit Akışı", value: "₺1.2M", color: "text-blue-400" },
                { label: "Risk Skoru", value: "87/100", color: "text-violet-400" },
              ].map((kpi) => (
                <div key={kpi.label} className="rounded-lg border border-white/8 bg-white/3 p-3">
                  <p className="text-xs text-muted-foreground">{kpi.label}</p>
                  <p className={`mt-1 text-lg font-bold tabular-nums ${kpi.color}`}>{kpi.value}</p>
                </div>
              ))}
            </div>

            {/* Mock chart area */}
            <div className="mx-4 mb-4 rounded-lg border border-white/8 bg-white/3 p-4">
              <div className="mb-3 flex items-center justify-between">
                <p className="text-xs font-medium">12 Aylık Tahmin — 3 Senaryo</p>
                <div className="flex gap-2 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-emerald-400" />Optimist</span>
                  <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-blue-400" />Baz</span>
                  <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-red-400" />Pesimist</span>
                </div>
              </div>
              {/* Fake sparkline bars */}
              <div className="flex h-16 items-end gap-1">
                {[40, 55, 48, 62, 58, 70, 65, 78, 72, 85, 80, 92].map((h, i) => (
                  <div key={i} className="flex-1 rounded-t-sm bg-primary/40" style={{ height: `${h}%` }} />
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── Social proof ──────────────────────────────────────────────────────────────

function SocialProof() {
  const stats = [
    { value: "12+",    label: "AI Ajan"              },
    { value: "5 dk",   label: "İlk Analize Kadar"    },
    { value: "941",    label: "Test Geçiyor"          },
    { value: "Logo Tiger, Paraşüt", label: "Entegrasyon" },
  ];

  return (
    <section className="border-y border-border bg-muted/20 py-12">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-2 gap-8 md:grid-cols-4">
          {stats.map((s) => (
            <div key={s.label} className="text-center">
              <p className="text-2xl font-bold tracking-tight text-foreground">{s.value}</p>
              <p className="mt-1 text-sm text-muted-foreground">{s.label}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── Features ──────────────────────────────────────────────────────────────────

const FEATURES = [
  {
    icon: DollarSign,
    title: "CFO Analizi",
    desc: "P&L, nakit akışı, bütçe sapması, vergi takvimi — tüm finansal tablolar otomatik.",
    color: "text-emerald-400",
    bg:   "bg-emerald-400/10",
  },
  {
    icon: Brain,
    title: "12 Aylık Tahmin",
    desc: "Monte Carlo simülasyonu ile optimist, baz ve pesimist senaryo karşılaştırması.",
    color: "text-violet-400",
    bg:   "bg-violet-400/10",
  },
  {
    icon: AlertTriangle,
    title: "Anomali Tespiti",
    desc: "Sahte ödeme, olağandışı tutar, tedarikçi yoğunlaşması — AI anlık işaretliyor.",
    color: "text-orange-400",
    bg:   "bg-orange-400/10",
  },
  {
    icon: Shield,
    title: "Risk & KRI",
    desc: "KRI gösterge paneli, ısı haritası, korelasyon matrisi ve bulaşma simülasyonu.",
    color: "text-red-400",
    bg:   "bg-red-400/10",
  },
  {
    icon: Activity,
    title: "Gerçek Zamanlı SSE",
    desc: "Analiz ajanları çalışırken her adımı canlı görün. Şeffaflık, kör nokta yok.",
    color: "text-blue-400",
    bg:   "bg-blue-400/10",
  },
  {
    icon: FileText,
    title: "Yönetici Raporları",
    desc: "Excel ve PDF raporlar otomatik üretilir, indirmeye hazır. Sıfır manuel iş.",
    color: "text-amber-400",
    bg:   "bg-amber-400/10",
  },
];

function Features() {
  return (
    <section id="özellikler" className="py-24">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mb-12 text-center">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Tek platformda tüm analiz ihtiyaçları
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Muhasebe verinizi yükleyin, AI ajanları saniyeler içinde devreye girer.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => {
            const Icon = f.icon;
            return (
              <div
                key={f.title}
                className="group rounded-xl border border-border bg-card p-6 transition-colors hover:border-primary/30"
              >
                <div className={`mb-4 inline-flex rounded-lg p-2.5 ${f.bg}`}>
                  <Icon className={`h-5 w-5 ${f.color}`} aria-hidden="true" />
                </div>
                <h3 className="mb-2 font-semibold">{f.title}</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">{f.desc}</p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ── C-Suite agents ─────────────────────────────────────────────────────────────

const AGENTS = [
  { role: "CFO",  color: "from-emerald-500 to-teal-600",   desc: "P&L, nakit akışı, tahmin, bütçe, vergi" },
  { role: "CEO",  color: "from-violet-500 to-purple-600",  desc: "OKR, stratejik öncelikler, yönetim kurulu sunumu" },
  { role: "CTO",  color: "from-blue-500 to-indigo-600",    desc: "Teknik borç, sistem sağlığı, sprint hızı" },
  { role: "COO",  color: "from-orange-500 to-amber-600",   desc: "Operasyon verimliliği, SLA, kaynak kullanımı" },
  { role: "CMO",  color: "from-pink-500 to-rose-600",      desc: "CAC, LTV, kampanya ROI, pazar büyümesi" },
  { role: "CHRO", color: "from-cyan-500 to-sky-600",       desc: "İşten ayrılma, ücret analizi, departman sağlığı" },
];

function AgentsSection() {
  return (
    <section id="ajanlar" className="py-24 bg-muted/10">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mb-12 text-center">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Her yönetici rolü için özel AI ajan
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Verilerinizi yükleyin — her ajan kendi uzmanlık alanında çalışır.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          {AGENTS.map((a) => (
            <div
              key={a.role}
              className="flex flex-col items-center rounded-xl border border-border bg-card p-4 text-center transition-colors hover:border-primary/30"
            >
              <div className={`mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br ${a.color}`}>
                <span className="text-sm font-bold text-white">{a.role}</span>
              </div>
              <p className="text-xs leading-relaxed text-muted-foreground">{a.desc}</p>
            </div>
          ))}
        </div>

        {/* Command center callout */}
        <div className="mt-8 rounded-xl border border-primary/20 bg-primary/5 p-6 text-center">
          <p className="text-sm font-medium">
            + <span className="text-primary">Command Center</span> — Tüm ajanların sonuçlarını tek ekranda birleştirir.
            Çapraz departman riskleri, hızlı kazanımlar ve şirket sağlık skoru.
          </p>
        </div>
      </div>
    </section>
  );
}

// ── Pricing ───────────────────────────────────────────────────────────────────

const PLANS = [
  {
    name: "Starter",
    price: "Ücretsiz",
    period: "",
    desc: "Küçük işletmeler ve deneme için",
    highlight: false,
    features: [
      "5 analiz / ay",
      "CFO & CEO ajanları",
      "PDF & Excel raporlar",
      "1 kullanıcı",
      "E-posta destek",
    ],
    cta: "Ücretsiz Başla",
    href: "/auth/register",
  },
  {
    name: "Growth",
    price: "₺2.990",
    period: "/ ay",
    desc: "Büyüyen şirketler için tam paket",
    highlight: true,
    features: [
      "Sınırsız analiz",
      "Tüm 12 C-Suite ajanı",
      "Anomali & risk modülleri",
      "5 kullanıcı",
      "API erişimi",
      "Öncelikli destek",
    ],
    cta: "14 Gün Deneyin",
    href: "/auth/register",
  },
  {
    name: "Enterprise",
    price: "Özel",
    period: "",
    desc: "Kurumsal müşteriler için özel çözüm",
    highlight: false,
    features: [
      "Sınırsız kullanıcı",
      "SSO / SAML",
      "White-label",
      "On-premise kurulum",
      "SLA garantisi",
      "Dedike müşteri başarı",
    ],
    cta: "Teklif Alın",
    href: "mailto:hello@clevelai.com",
  },
];

function Pricing() {
  return (
    <section id="fiyatlandırma" className="py-24">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mb-12 text-center">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Şeffaf fiyatlandırma
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Kredi kartı olmadan deneyin. İstediğiniz zaman iptal edin.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {PLANS.map((plan) => (
            <div
              key={plan.name}
              className={`relative flex flex-col rounded-2xl border p-6 ${
                plan.highlight
                  ? "border-primary bg-primary/5 shadow-lg shadow-primary/10"
                  : "border-border bg-card"
              }`}
            >
              {plan.highlight && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                  <span className="rounded-full bg-primary px-3 py-1 text-xs font-semibold text-primary-foreground">
                    En Popüler
                  </span>
                </div>
              )}

              <div className="mb-4">
                <h3 className="text-lg font-bold">{plan.name}</h3>
                <p className="mt-0.5 text-sm text-muted-foreground">{plan.desc}</p>
              </div>

              <div className="mb-6 flex items-baseline gap-1">
                <span className="text-3xl font-bold">{plan.price}</span>
                {plan.period && <span className="text-sm text-muted-foreground">{plan.period}</span>}
              </div>

              <ul className="mb-8 flex-1 space-y-2.5">
                {plan.features.map((f) => (
                  <li key={f} className="flex items-start gap-2 text-sm">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                    <span className="text-muted-foreground">{f}</span>
                  </li>
                ))}
              </ul>

              <Link
                href={plan.href}
                className={`flex items-center justify-center gap-1.5 rounded-lg px-4 py-2.5 text-sm font-semibold transition-opacity hover:opacity-90 ${
                  plan.highlight
                    ? "bg-primary text-primary-foreground"
                    : "border border-border text-foreground hover:border-primary/40"
                }`}
              >
                {plan.cta}
                <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </Link>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── CTA band ──────────────────────────────────────────────────────────────────

function CTABand() {
  return (
    <section className="relative overflow-hidden py-24">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          background: "radial-gradient(ellipse at center, oklch(0.62 0.26 262 / 0.12) 0%, transparent 70%)",
        }}
      />
      <div className="relative mx-auto max-w-4xl px-4 text-center sm:px-6 lg:px-8">
        <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
          5 dakikada ilk C-Suite analizinizi alın
        </h2>
        <p className="mt-4 text-lg text-muted-foreground">
          Muhasebe CSV'nizi yükleyin. AI ajanları devreye girer. <br />
          CFO raporu, risk analizi, 12 aylık tahmin — hepsi otomatik.
        </p>
        <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
          <Link
            href="/auth/register"
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-8 py-3.5 text-base font-semibold text-primary-foreground transition-opacity hover:opacity-90"
          >
            Ücretsiz Başla
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </div>
        <p className="mt-3 text-sm text-muted-foreground">
          Logo Tiger · Paraşüt · GİB e-Fatura desteklenir
        </p>
      </div>
    </section>
  );
}

// ── Footer ────────────────────────────────────────────────────────────────────

function Footer() {
  return (
    <footer className="border-t border-border py-12">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col items-center justify-between gap-4 sm:flex-row">
          <Logo size="sm" />
          <p className="text-sm text-muted-foreground">
            © 2025 C-Level AI. Tüm hakları saklıdır.
          </p>
          <div className="flex gap-4 text-sm text-muted-foreground">
            <a href="#" className="transition-colors hover:text-foreground">Gizlilik</a>
            <a href="#" className="transition-colors hover:text-foreground">Kullanım Şartları</a>
            <a href="mailto:hello@clevelai.com" className="transition-colors hover:text-foreground">İletişim</a>
          </div>
        </div>
      </div>
    </footer>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <Navbar />
      <main>
        <Hero />
        <SocialProof />
        <Features />
        <AgentsSection />
        <Pricing />
        <CTABand />
      </main>
      <Footer />
    </div>
  );
}
