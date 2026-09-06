"use client";

import { useState, useEffect } from "react";
import { useSession } from "next-auth/react";
import Link from "next/link";
import {
  Upload, Building2, Sparkles, BarChart3, Brain,
  CheckCircle2, ChevronRight, X, ArrowRight, Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { STORAGE_PREFIX } from "@/lib/branding";

// ── Step definitions ──────────────────────────────────────────────────────────

const ONBOARDING_STEPS = [
  {
    id:      "welcome",
    icon:    Sparkles,
    color:   "text-primary",
    bg:      "bg-primary/10",
    title:   "Agentic CFO'ya Hoş Geldiniz",
    subtitle: "Türkiye'nin ilk C-Suite AI platformu",
    desc:    "Finansal verilerinizi yükleyin, 12 AI ajan saniyeler içinde CFO, CTO, CMO, COO ve CHRO analizlerini paralel olarak çalıştırsın.",
    cta:     "Başlayalım",
    href:    null,
    features: [
      "Gerçek zamanlı finansal analiz",
      "Cross-domain risk tespiti",
      "Board deck otomatik oluşturma",
      "Türkçe AI raporlama",
    ],
  },
  {
    id:      "upload",
    icon:    Upload,
    color:   "text-blue-400",
    bg:      "bg-blue-500/10",
    title:   "Finansal Verilerinizi Yükleyin",
    subtitle: "1. Adım — Veri",
    desc:    "Banka ekstresi, muhasebe CSV'si veya ERP çıktısı yükleyin. Paraşüt ve Logo Tiger entegrasyonlarımız da mevcuttur.",
    cta:     "Veri Yükle",
    href:    "/upload",
    features: [
      "CSV, Excel, PDF destekli",
      "Paraşüt OAuth2 entegrasyonu",
      "Logo Tiger CSV import",
      "Otomatik sütun tespiti",
    ],
  },
  {
    id:      "analyze",
    icon:    BarChart3,
    color:   "text-emerald-400",
    bg:      "bg-emerald-500/10",
    title:   "Analizi Başlatın",
    subtitle: "2. Adım — Analiz",
    desc:    "CFO pipeline otomatik olarak P&L, nakit akışı, anomali tespiti ve 12 aylık tahmin üretir. Ortalama süre: 45 saniye.",
    cta:     "Analizi Başlat",
    href:    "/upload",
    features: [
      "P&L + Cash Flow analizi",
      "Anomali ve fraud tespiti",
      "12 aylık tahmin",
      "Bütçe sapma analizi",
    ],
  },
  {
    id:      "intelligence",
    icon:    Brain,
    color:   "text-purple-400",
    bg:      "bg-purple-500/10",
    title:   "C-Suite Intelligence'ı Keşfedin",
    subtitle: "3. Adım — Derinleşin",
    desc:    "Cross-Domain Intelligence Hub tüm C-Suite verilerini birleştirerek gizli riskleri ve fırsatları ortaya çıkarır.",
    cta:     "Intelligence Aç",
    href:    "/intelligence",
    features: [
      "SWOT otomatik analizi",
      "Sektör benchmark karşılaştırması",
      "Proaktif KRI alertleri",
      "Board Deck PDF export",
    ],
  },
  {
    id:      "workspace",
    icon:    Building2,
    color:   "text-orange-400",
    bg:      "bg-orange-500/10",
    title:   "Ekibinizi Davet Edin",
    subtitle: "4. Adım — İşbirliği",
    desc:    "Workspace oluşturun, CFO/CTO/CEO rollerinizi tanımlayın ve ekibinizle aynı veri üzerinde çalışın.",
    cta:     "Workspace Kur",
    href:    "/settings/workspace",
    features: [
      "Çoklu kullanıcı desteği",
      "Rol tabanlı erişim",
      "SMMM muhasebeci portal",
      "Ortak analiz geçmişi",
    ],
  },
] as const;

const STORAGE_KEY    = `${STORAGE_PREFIX}_onboarding_dismissed`;
const WIZARD_STORAGE = `${STORAGE_PREFIX}_onboarding_wizard_shown`;

// ── Feature chip ──────────────────────────────────────────────────────────────

function FeatureChip({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <CheckCircle2 className="h-3 w-3 text-emerald-400 shrink-0" />
      {text}
    </div>
  );
}

// ── Full-screen Wizard Modal ──────────────────────────────────────────────────

interface WizardModalProps {
  onClose: () => void;
}

function WizardModal({ onClose }: WizardModalProps) {
  const [step, setStep] = useState(0);
  const total = ONBOARDING_STEPS.length;
  const current = ONBOARDING_STEPS[step];
  const Icon = current.icon;
  const isLast = step === total - 1;

  function handleNext() {
    if (isLast) {
      onClose();
    } else {
      setStep((s) => s + 1);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Başlangıç rehberi"
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4"
    >
      <Card className="w-full max-w-lg p-0 overflow-hidden shadow-xl">
        {/* Progress bar */}
        <div className="h-1 bg-muted">
          <div
            className="h-full bg-primary transition-all duration-500"
            style={{ width: `${((step + 1) / total) * 100}%` }}
          />
        </div>

        <div className="p-6 space-y-5">
          {/* Close button */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground font-medium">
              {current.subtitle} ({step + 1}/{total})
            </span>
            <button
              onClick={onClose}
              className="rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              aria-label="Rehberi kapat"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Icon + Title */}
          <div className="flex items-center gap-4">
            <div className={cn("rounded-xl p-3", current.bg)}>
              <Icon className={cn("h-7 w-7", current.color)} />
            </div>
            <div>
              <h2 className="text-lg font-bold">{current.title}</h2>
              <p className="text-sm text-muted-foreground mt-1 leading-relaxed">{current.desc}</p>
            </div>
          </div>

          {/* Features */}
          <div className="grid grid-cols-2 gap-2 rounded-lg bg-muted/30 p-3">
            {current.features.map((f) => (
              <FeatureChip key={f} text={f} />
            ))}
          </div>

          {/* Step dots */}
          <div className="flex items-center justify-center gap-1.5">
            {ONBOARDING_STEPS.map((_, i) => (
              <button
                key={i}
                onClick={() => setStep(i)}
                className={cn(
                  "rounded-full transition-all",
                  i === step
                    ? "w-6 h-1.5 bg-primary"
                    : i < step
                    ? "w-1.5 h-1.5 bg-primary/50"
                    : "w-1.5 h-1.5 bg-muted-foreground/30 hover:bg-muted-foreground/50"
                )}
                aria-label={`Adım ${i + 1}`}
                aria-current={i === step ? "step" : undefined}
              />
            ))}
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            {current.href ? (
              <Link href={current.href} onClick={onClose} className="flex-1">
                <Button className="w-full" size="lg">
                  {current.cta}
                  <ArrowRight className="h-4 w-4 ml-1.5" />
                </Button>
              </Link>
            ) : (
              <Button className="flex-1" size="lg" onClick={handleNext}>
                {current.cta}
                <ArrowRight className="h-4 w-4 ml-1.5" />
              </Button>
            )}
            {!isLast && (
              <Button variant="ghost" size="lg" onClick={handleNext}>
                Atla
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            )}
            {isLast && (
              <Button variant="outline" size="lg" onClick={onClose}>
                Kapat
              </Button>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}

// ── Top banner (shown after wizard is dismissed) ──────────────────────────────

const BANNER_STEPS = [
  { id: "upload",    icon: Upload,    title: "Veri yükleyin",        desc: "CSV, Excel veya PDF muhasebe dosyanızı yükleyin.", href: "/upload",                cta: "Dosya Yükle" },
  { id: "workspace", icon: Building2, title: "Workspace kurun",      desc: "Ekibinizi davet edin, birlikte çalışın.",          href: "/settings/workspace",    cta: "Ekibi Davet Et" },
  { id: "analyze",   icon: Sparkles,  title: "AI analizi başlatın",  desc: "12 ajan devreye girer, 5 dakikada tam rapor.",     href: "/upload",                cta: "Analiz Başlat" },
  { id: "intel",     icon: Zap,       title: "Intelligence görün",   desc: "Cross-domain risk ve fırsatları keşfedin.",        href: "/intelligence",          cta: "Keşfet" },
] as const;

function TopBanner({ onDismiss }: { onDismiss: () => void }) {
  const [activeStep, setActiveStep] = useState(0);
  const step = BANNER_STEPS[activeStep];
  const StepIcon = step.icon;

  return (
    <div
      role="region"
      aria-label="Getting started"
      className="relative border-b border-primary/20 bg-gradient-to-r from-primary/8 via-primary/5 to-transparent"
    >
      <div className="mx-auto flex max-w-screen-xl items-center gap-4 px-4 py-3 sm:px-6">
        <div className="hidden shrink-0 sm:block">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/15">
            <StepIcon className="h-4 w-4 text-primary" aria-hidden="true" />
          </div>
        </div>

        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-primary">
            Başlangıç rehberi — Adım {activeStep + 1}/{BANNER_STEPS.length}
          </p>
          <p className="mt-0.5 text-sm font-medium">
            {step.title}
            <span className="ml-1.5 text-muted-foreground font-normal">{step.desc}</span>
          </p>
        </div>

        <div className="hidden items-center gap-1 sm:flex">
          {BANNER_STEPS.map((s, i) => (
            <button
              key={s.id}
              onClick={() => setActiveStep(i)}
              className={cn(
                "h-1.5 rounded-full transition-all",
                i === activeStep ? "w-4 bg-primary" : "w-1.5 bg-primary/30 hover:bg-primary/50"
              )}
              aria-label={`Adım ${i + 1}: ${s.title}`}
              aria-current={i === activeStep ? "step" : undefined}
            />
          ))}
        </div>

        <Link
          href={step.href}
          className="flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground transition-opacity hover:opacity-90"
        >
          {step.cta}
          <ArrowRight className="h-3 w-3" aria-hidden="true" />
        </Link>

        {activeStep < BANNER_STEPS.length - 1 && (
          <button
            onClick={() => setActiveStep((s) => s + 1)}
            className="hidden shrink-0 text-xs text-muted-foreground transition-colors hover:text-foreground sm:block"
          >
            Sonraki →
          </button>
        )}

        <button
          onClick={onDismiss}
          className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:text-foreground"
          aria-label="Başlangıç rehberini kapat"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

export function OnboardingBanner() {
  const { data: session } = useSession();
  const [state, setState] = useState<"hidden" | "wizard" | "banner">("hidden");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const bannerDismissed = localStorage.getItem(STORAGE_KEY) === "1";
    const wizardShown     = localStorage.getItem(WIZARD_STORAGE) === "1";

    if (bannerDismissed) {
      setState("hidden");
    } else if (!wizardShown) {
      setState("wizard");
    } else {
      setState("banner");
    }
  }, []);

  function handleWizardClose() {
    if (typeof window !== "undefined") {
      localStorage.setItem(WIZARD_STORAGE, "1");
    }
    setState("banner");
  }

  function handleBannerDismiss() {
    if (typeof window !== "undefined") {
      localStorage.setItem(STORAGE_KEY, "1");
    }
    setState("hidden");
  }

  if (!session || state === "hidden") return null;
  if (state === "wizard") return <WizardModal onClose={handleWizardClose} />;
  return <TopBanner onDismiss={handleBannerDismiss} />;
}
