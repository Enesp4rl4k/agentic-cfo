import {
  DollarSign,
  Brain,
  AlertTriangle,
  Shield,
  Activity,
  FileText,
  TrendingUp,
  Layers,
  GitBranch,
  Zap,
} from "lucide-react";

const FEATURES = [
  {
    icon: DollarSign,
    title: "CFO Analizi",
    desc: "P&L, nakit akışı, bütçe sapması, vergi takvimi — tüm finansal tablolar tek tıkla otomatik üretilir.",
    color: "text-sage-400",
    bg: "bg-sage-400/10",
    border: "group-hover:border-sage-500/30",
    glow: "group-hover:shadow-sage-500/10",
  },
  {
    icon: Brain,
    title: "Monte Carlo Tahmini",
    desc: "1000+ senaryo simülasyonu ile 12 aylık optimist, baz ve pesimist tahmin. Hayatta kalma oranı hesaplama.",
    color: "text-brass-400",
    bg: "bg-brass-400/10",
    border: "group-hover:border-brass-500/30",
    glow: "group-hover:shadow-brass-500/10",
  },
  {
    icon: AlertTriangle,
    title: "Anomali Tespiti",
    desc: "Sahte ödeme, olağandışı tutar, tedarikçi yoğunlaşması — AI her sahtekarlık sinyalini anlık işaretler.",
    color: "text-copper-400",
    bg: "bg-copper-400/10",
    border: "group-hover:border-copper-500/30",
    glow: "group-hover:shadow-copper-500/10",
  },
  {
    icon: Shield,
    title: "Risk & KRI Paneli",
    desc: "KRI gösterge paneli, ısı haritası, korelasyon matrisi ve çapraz-domain bulaşma simülasyonu.",
    color: "text-red-400",
    bg: "bg-red-400/10",
    border: "group-hover:border-red-500/30",
    glow: "group-hover:shadow-red-500/10",
  },
  {
    icon: Activity,
    title: "Gerçek Zamanlı SSE",
    desc: "Analiz ajanları çalışırken her adımı canlı görün. Şeffaflık var, kör nokta yok.",
    color: "text-mapblue-400",
    bg: "bg-mapblue-400/10",
    border: "group-hover:border-mapblue-500/30",
    glow: "group-hover:shadow-mapblue-500/10",
  },
  {
    icon: FileText,
    title: "Otomatik Raporlar",
    desc: "Excel ve PDF raporlar otomatik üretilir, indirmeye hazır. Yönetim kurulu sunumu dahil.",
    color: "text-parchment-400",
    bg: "bg-parchment-400/10",
    border: "group-hover:border-parchment-500/30",
    glow: "group-hover:shadow-parchment-500/10",
  },
  {
    icon: TrendingUp,
    title: "Benchmark Analizi",
    desc: "Sektör medyanı, P25/P75 karşılaştırması. Şirketiniz rakiplerine göre nerede duruyor?",
    color: "text-clay-400",
    bg: "bg-clay-400/10",
    border: "group-hover:border-clay-500/30",
    glow: "group-hover:shadow-clay-500/10",
  },
  {
    icon: Layers,
    title: "Working Capital",
    desc: "DSO, DPO, DIO ve Cash Conversion Cycle analizi. Nakit serbest bırakma fırsatlarını tespit edin.",
    color: "text-brass-400",
    bg: "bg-brass-400/10",
    border: "group-hover:border-brass-500/30",
    glow: "group-hover:shadow-brass-500/10",
  },
  {
    icon: GitBranch,
    title: "ERP & Open Banking",
    desc: "Logo Tiger, Paraşüt, GİB e-Fatura, Open Banking ve e-ticaret platformlarıyla senkronizasyon.",
    color: "text-mapblue-400",
    bg: "bg-mapblue-400/10",
    border: "group-hover:border-mapblue-500/30",
    glow: "group-hover:shadow-mapblue-500/10",
  },
];

export function FeaturesGrid() {
  return (
    <section id="özellikler" className="relative py-24">
      {/* Background accent */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 60% 40% at 20% 50%, oklch(0.74 0.13 82 / 0.06) 0%, transparent 70%)",
        }}
      />

      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        {/* Section header */}
        <div className="mb-14 text-center">
          <div className="mb-3 flex justify-center">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/6 px-3 py-1 text-xs font-medium text-primary">
              <Zap className="h-3 w-3" aria-hidden="true" />
              Platform Özellikleri
            </span>
          </div>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Tek platformda tüm analiz ihtiyaçları
          </h2>
          <p className="mt-3 mx-auto max-w-2xl text-lg text-muted-foreground">
            Muhasebe verinizi yükleyin, AI ajanları saniyeler içinde devreye girer.
            Manuel iş sıfır, içgörü sonsuz.
          </p>
        </div>

        {/* Features grid — 3 col on desktop */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f, i) => {
            const Icon = f.icon;
            return (
              <div
                key={f.title}
                className={`group relative overflow-hidden rounded-xl border border-border bg-card p-5 transition-all duration-200 hover-lift ${f.border} hover:shadow-lg ${f.glow}`}
                style={{
                  animation: "slide-up 400ms var(--ease-out-expo) both",
                  animationDelay: `${i * 40}ms`,
                }}
              >
                {/* Subtle corner glow on hover */}
                <div
                  aria-hidden="true"
                  className="pointer-events-none absolute -right-8 -top-8 h-24 w-24 rounded-full opacity-0 blur-2xl transition-opacity duration-300 group-hover:opacity-100"
                  style={{ background: `var(--tw-gradient-from, transparent)` }}
                />

                {/* Icon */}
                <div className={`mb-3 inline-flex rounded-lg p-2.5 ${f.bg}`}>
                  <Icon className={`h-5 w-5 ${f.color}`} aria-hidden="true" />
                </div>

                {/* Text */}
                <h3 className="mb-1.5 font-semibold text-foreground">{f.title}</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">{f.desc}</p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
