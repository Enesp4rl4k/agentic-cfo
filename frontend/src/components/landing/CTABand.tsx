import Link from "next/link";
import { ArrowRight, Upload, BarChart3, FileText } from "lucide-react";

const STEPS = [
  {
    icon: Upload,
    step: "01",
    title: "CSV Yükle",
    desc: "Logo Tiger, Paraşüt veya herhangi bir muhasebe programından dışa aktardığınız CSV.",
    color: "text-violet-400",
    bg: "bg-violet-400/10",
  },
  {
    icon: BarChart3,
    step: "02",
    title: "AI Analiz Eder",
    desc: "12 AI ajan paralel çalışır: CFO, CEO, CTO, CMO, COO, CHRO ve daha fazlası.",
    color: "text-blue-400",
    bg: "bg-blue-400/10",
  },
  {
    icon: FileText,
    step: "03",
    title: "Rapor Al",
    desc: "Kurumsal kalitede PDF raporlar, board deck ve yönetici özetleri otomatik hazır.",
    color: "text-emerald-400",
    bg: "bg-emerald-400/10",
  },
];

export function CTABand() {
  return (
    <section className="relative overflow-hidden py-24">
      {/* Background glow */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 70% 50% at 50% 50%, oklch(0.62 0.26 262 / 0.10) 0%, transparent 70%)",
        }}
      />

      {/* Animated gradient border at top */}
      <div
        aria-hidden="true"
        className="absolute inset-x-0 top-0 h-px"
        style={{
          background:
            "linear-gradient(90deg, transparent 0%, oklch(0.62 0.26 262 / 0.6) 50%, transparent 100%)",
        }}
      />

      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">

        {/* How it works */}
        <div className="mb-16">
          <p className="mb-8 text-center text-xs font-medium uppercase tracking-widest text-muted-foreground">
            3 Adımda Başlayın
          </p>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
            {STEPS.map((s, i) => {
              const Icon = s.icon;
              return (
                <div key={s.step} className="relative flex flex-col items-center text-center">
                  {/* Connector line */}
                  {i < STEPS.length - 1 && (
                    <div
                      aria-hidden="true"
                      className="absolute left-[calc(50%+3rem)] top-5 hidden h-px w-full sm:block"
                      style={{
                        background:
                          "linear-gradient(90deg, oklch(0.35 0.02 262), transparent)",
                        width: "calc(100% - 3rem)",
                      }}
                    />
                  )}

                  <div className={`mb-4 inline-flex rounded-xl p-3 ${s.bg}`}>
                    <Icon className={`h-6 w-6 ${s.color}`} aria-hidden="true" />
                  </div>
                  <p className="text-xs font-semibold text-muted-foreground">{s.step}</p>
                  <h3 className="mt-1 font-semibold text-foreground">{s.title}</h3>
                  <p className="mt-1.5 text-sm text-muted-foreground leading-relaxed">{s.desc}</p>
                </div>
              );
            })}
          </div>
        </div>

        {/* CTA card */}
        <div
          className="overflow-hidden rounded-2xl border border-primary/20 text-center"
          style={{
            background:
              "linear-gradient(135deg, oklch(0.15 0.030 262), oklch(0.13 0.025 255))",
            boxShadow: "0 0 60px oklch(0.62 0.26 262 / 0.12)",
          }}
        >
          {/* Top glow strip */}
          <div
            aria-hidden="true"
            className="h-px w-full"
            style={{
              background:
                "linear-gradient(90deg, transparent, oklch(0.62 0.26 262 / 0.5), transparent)",
            }}
          />

          <div className="px-6 py-12 sm:px-12">
            <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
              5 dakikada ilk C-Suite analizinizi alın
            </h2>
            <p className="mt-4 mx-auto max-w-xl text-lg text-muted-foreground">
              Muhasebe CSV&apos;nizi yükleyin. AI ajanları devreye girer.
              CFO raporu, risk analizi, 12 aylık tahmin — hepsi otomatik.
            </p>

            <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
              <Link
                href="/auth/register"
                className="inline-flex h-12 items-center gap-2 rounded-lg bg-primary px-8 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 press-feedback focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Ücretsiz Başla
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Link>
              <Link
                href="/auth/login"
                className="inline-flex h-12 items-center gap-2 rounded-lg border border-white/15 px-8 text-sm font-medium text-foreground transition-colors hover:border-white/30 hover:bg-white/5 press-feedback"
              >
                Demo İzle
              </Link>
            </div>

            <p className="mt-4 text-sm text-muted-foreground">
              Logo Tiger · Paraşüt · GİB e-Fatura · Open Banking desteklenir
            </p>
          </div>
        </div>
      </div>

      {/* Bottom border */}
      <div
        aria-hidden="true"
        className="absolute inset-x-0 bottom-0 h-px"
        style={{
          background:
            "linear-gradient(90deg, transparent 0%, oklch(0.62 0.26 262 / 0.2) 50%, transparent 100%)",
        }}
      />
    </section>
  );
}
