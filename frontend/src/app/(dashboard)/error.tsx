"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import {
  AlertTriangle, RefreshCw, LayoutDashboard, Upload,
  DollarSign, Cpu, Megaphone, Users, Layers, Crown,
  Shield, FileSearch, ShieldCheck, Wifi, WifiOff,
} from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";

interface ErrorPageProps {
  error: Error & { digest?: string };
  reset: () => void;
}

// ── Agent page metadata ───────────────────────────────────────────────────────

interface AgentMeta {
  name: string;
  icon: React.ElementType;
  color: string;
  hint: string;
  uploadRequired?: boolean;
}

const AGENT_META: Record<string, AgentMeta> = {
  "/pnl":        { name: "P&L Analizi",      icon: DollarSign, color: "text-emerald-400", hint: "P&L verisi hesaplanırken bir sorun oluştu. Analiz dosyanızı yeniden yükleyebilirsiniz." },
  "/cashflow":   { name: "Nakit Akışı",       icon: DollarSign, color: "text-blue-400",    hint: "Nakit akışı verileri yüklenirken hata oluştu. Sayfayı yenileyin veya analizi yeniden başlatın." },
  "/forecast":   { name: "Tahmin",            icon: DollarSign, color: "text-violet-400",  hint: "Tahmin modeli çalıştırılırken bir sorun oluştu. Bu geçici bir hata olabilir, tekrar deneyin." },
  "/budget":     { name: "Bütçe",             icon: DollarSign, color: "text-amber-400",   hint: "Bütçe analizi yüklenemedi. Analiz tamamlandıktan sonra tekrar erişmeyi deneyin." },
  "/tax":        { name: "Vergi",             icon: DollarSign, color: "text-orange-400",  hint: "Vergi hesaplama modülünde bir sorun oluştu." },
  "/cfo":        { name: "CFO Görünümü",      icon: DollarSign, color: "text-emerald-400", hint: "CFO dashboard verisi yüklenemedi. Önce bir analiz dosyası yüklemeniz gerekebilir.", uploadRequired: true },
  "/cto":        { name: "CTO Görünümü",      icon: Cpu,        color: "text-blue-400",    hint: "CTO analizi çalışırken bir hata oluştu. CSV verilerinizi kontrol edip tekrar deneyin." },
  "/ceo":        { name: "CEO Görünümü",      icon: Crown,      color: "text-yellow-400",  hint: "CEO sentezi için önce CFO analizi tamamlanmış olmalıdır." },
  "/cmo":        { name: "CMO Görünümü",      icon: Megaphone,  color: "text-purple-400",  hint: "Pazarlama analizi yüklenirken bir sorun oluştu." },
  "/coo":        { name: "COO Görünümü",      icon: Layers,     color: "text-orange-400",  hint: "Operasyonel analiz verisi alınamadı." },
  "/chro":       { name: "CHRO Görünümü",     icon: Users,      color: "text-pink-400",    hint: "İK analizi yüklenirken bir hata oluştu." },
  "/risk":       { name: "Risk",              icon: Shield,     color: "text-red-400",      hint: "Risk analizi verileri alınamadı. CFO analizi tamamlandıysa otomatik tetiklenmiş olmalıdır." },
  "/audit":      { name: "İç Denetim",        icon: FileSearch, color: "text-indigo-400",  hint: "Denetim modülü yüklenemedi." },
  "/compliance": { name: "Uyumluluk",         icon: ShieldCheck,color: "text-cyan-400",    hint: "Uyumluluk kontrolleri yüklenirken bir sorun oluştu." },
  "/anomalies":  { name: "Anomaliler",        icon: AlertTriangle, color: "text-amber-400", hint: "Anomali tespiti verisi alınamadı." },
  "/command-center": { name: "Command Center", icon: LayoutDashboard, color: "text-primary", hint: "Command Center verileri yüklenemedi. Tüm agent analizleri hazır olmayabilir." },
};

// ── Error type classification ─────────────────────────────────────────────────

type ErrorCategory = "network" | "auth" | "notfound" | "agent" | "unknown";

function classifyError(error: Error): ErrorCategory {
  const msg = error.message?.toLowerCase() ?? "";
  if (msg.includes("fetch") || msg.includes("network") || msg.includes("econnrefused") || msg.includes("timeout")) {
    return "network";
  }
  if (msg.includes("401") || msg.includes("unauthorized") || msg.includes("forbidden") || msg.includes("403")) {
    return "auth";
  }
  if (msg.includes("404") || msg.includes("not found")) {
    return "notfound";
  }
  if (msg.includes("agent") || msg.includes("pipeline") || msg.includes("llm") || msg.includes("openai")) {
    return "agent";
  }
  return "unknown";
}

interface ErrorCategoryConfig {
  title: string;
  description: string;
  icon: React.ElementType;
}

const ERROR_CATEGORY_CONFIG: Record<ErrorCategory, ErrorCategoryConfig> = {
  network:  { title: "Bağlantı hatası",     description: "Backend servisiyle iletişim kurulamadı. İnternet bağlantınızı ve backend'in çalıştığını kontrol edin.", icon: WifiOff },
  auth:     { title: "Yetkilendirme hatası", description: "Bu sayfaya erişim yetkiniz yok veya oturumunuz sona ermiş.", icon: Shield },
  notfound: { title: "Veri bulunamadı",      description: "Analiz verisi henüz hazır değil. Önce bir dosya yükleyip analizi başlatın.", icon: Upload },
  agent:    { title: "AI agent hatası",      description: "AI analiz pipeline'ında beklenmedik bir sorun oluştu. Bu geçici olabilir.", icon: AlertTriangle },
  unknown:  { title: "Beklenmedik hata",     description: "Bu bölümde beklenmedik bir hata oluştu.", icon: AlertTriangle },
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function DashboardError({ error, reset }: ErrorPageProps) {
  const pathname = usePathname();

  // Find the most specific matching agent path
  const agentKey = Object.keys(AGENT_META)
    .sort((a, b) => b.length - a.length) // longest match first
    .find((key) => pathname.startsWith(key));

  const agentMeta = agentKey ? AGENT_META[agentKey] : null;
  const errorCategory = classifyError(error);
  const categoryConfig = ERROR_CATEGORY_CONFIG[errorCategory];

  const AgentIcon = agentMeta?.icon ?? AlertTriangle;
  const CategoryIcon = categoryConfig.icon;

  useEffect(() => {
    // In production: report to Sentry or other error tracking
    // if (process.env.NODE_ENV === "production") {
    //   Sentry.captureException(error, { extra: { pathname, agentKey } });
    // }
    if (process.env.NODE_ENV === "development") {
      console.error("[DashboardError boundary]", {
        pathname,
        agentKey,
        errorCategory,
        message: error.message,
        digest: error.digest,
        stack: error.stack,
      });
    }
  }, [error, pathname, agentKey, errorCategory]);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center p-8 text-center">
      <div className="w-full max-w-md">

        {/* Agent context badge */}
        {agentMeta && (
          <div className="mb-4 flex justify-center">
            <div className={cn(
              "flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-xs font-medium",
              agentMeta.color
            )}>
              <AgentIcon className="h-3.5 w-3.5" aria-hidden="true" />
              {agentMeta.name}
            </div>
          </div>
        )}

        {/* Error icon */}
        <div className="mb-4 flex justify-center">
          <div className={cn(
            "rounded-full p-3",
            errorCategory === "network" ? "bg-amber-500/10" :
            errorCategory === "auth"    ? "bg-orange-500/10" :
            "bg-destructive/10"
          )}>
            <CategoryIcon
              className={cn(
                "h-7 w-7",
                errorCategory === "network" ? "text-amber-400" :
                errorCategory === "auth"    ? "text-orange-400" :
                "text-destructive"
              )}
              aria-hidden="true"
            />
          </div>
        </div>

        {/* Title + description */}
        <h2 className="mb-1 text-lg font-bold">{categoryConfig.title}</h2>
        <p className="mb-2 text-sm text-muted-foreground leading-relaxed">
          {categoryConfig.description}
        </p>

        {/* Agent-specific hint */}
        {agentMeta && (
          <p className="mb-4 text-xs text-muted-foreground/70 leading-relaxed max-w-xs mx-auto">
            {agentMeta.hint}
          </p>
        )}

        {/* Error digest (always shown) */}
        {error.digest && (
          <p className="mb-4 font-mono text-[10px] text-muted-foreground/50">
            ref: {error.digest}
          </p>
        )}

        {/* Dev-only stack trace */}
        {process.env.NODE_ENV === "development" && error.message && (
          <details className="mb-4 text-left">
            <summary className="mb-1 cursor-pointer text-xs text-muted-foreground hover:text-foreground">
              Hata detayı (dev only)
            </summary>
            <pre className="overflow-auto rounded-md bg-muted/50 p-3 text-[11px] text-muted-foreground max-h-32">
              {error.message}
            </pre>
          </details>
        )}

        {/* Actions */}
        <div className="flex flex-col items-center gap-2 sm:flex-row sm:justify-center">
          <button
            onClick={reset}
            className={cn(
              "inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2",
              "text-sm font-semibold text-primary-foreground",
              "transition-opacity hover:opacity-90",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            )}
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            Tekrar Dene
          </button>

          {/* Upload CTA for pages that need data */}
          {(agentMeta?.uploadRequired || errorCategory === "notfound") && (
            <Link
              href="/upload"
              className={cn(
                "inline-flex items-center gap-2 rounded-lg border border-primary/30",
                "bg-primary/10 px-4 py-2 text-sm font-medium text-primary",
                "transition-colors hover:bg-primary/15",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              )}
            >
              <Upload className="h-3.5 w-3.5" aria-hidden="true" />
              Veri Yükle
            </Link>
          )}

          <Link
            href="/"
            className={cn(
              "inline-flex items-center gap-2 rounded-lg border border-border px-4 py-2",
              "text-sm font-medium text-muted-foreground",
              "transition-colors hover:border-primary/30 hover:text-foreground",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            )}
          >
            <LayoutDashboard className="h-3.5 w-3.5" aria-hidden="true" />
            Ana Panel
          </Link>
        </div>

        {/* Network error helper */}
        {errorCategory === "network" && (
          <div className="mt-4 flex items-center justify-center gap-1.5 text-xs text-muted-foreground/60">
            <Wifi className="h-3 w-3" aria-hidden="true" />
            <span>
              Backend servisi:{" "}
              <code className="font-mono">
                {process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}
              </code>
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
