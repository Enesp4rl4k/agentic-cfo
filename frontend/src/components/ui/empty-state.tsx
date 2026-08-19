"use client";
/**
 * EmptyState — Animated empty state component with Lottie support.
 *
 * Usage:
 *   <EmptyState
 *     preset="empty"
 *     title="Henüz analiz yok"
 *     description="Başlamak için bir finansal belge yükleyin."
 *     action={<Button>Veri Yükle</Button>}
 *   />
 */

import { type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { LottiePlayer, type LottiePreset } from "./lottie-player";

// ── Types ─────────────────────────────────────────────────────────────────────

interface EmptyStateProps {
  /** Lottie animation preset */
  preset?: LottiePreset;
  /** Icon to show if no Lottie (overridden by preset) */
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  secondaryAction?: ReactNode;
  className?: string;
  /** Animation size in px (default: 120) */
  animationSize?: number;
  /** Card-style container (default: true) */
  card?: boolean;
  /** Compact variant — smaller padding */
  compact?: boolean;
}

// ── Empty state illustrations (CSS-only fallback icons) ───────────────────────

function InboxIcon() {
  return (
    <svg
      width="48"
      height="48"
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
      className="text-muted-foreground/40"
    >
      <rect x="6" y="8" width="36" height="32" rx="4" stroke="currentColor" strokeWidth="1.5" fill="currentColor" fillOpacity="0.04" />
      <path d="M6 28h10l4 4h8l4-4h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M18 18h12M18 23h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg width="48" height="48" viewBox="0 0 48 48" fill="none" aria-hidden="true" className="text-muted-foreground/40">
      <circle cx="20" cy="20" r="12" stroke="currentColor" strokeWidth="1.5" fill="currentColor" fillOpacity="0.04" />
      <path d="M29 29l9 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function ChartIcon() {
  return (
    <svg width="48" height="48" viewBox="0 0 48 48" fill="none" aria-hidden="true" className="text-muted-foreground/40">
      <rect x="6" y="8" width="36" height="32" rx="4" stroke="currentColor" strokeWidth="1.5" fill="currentColor" fillOpacity="0.04" />
      <path d="M13 30l8-8 8 6 6-10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function EmptyState({
  preset,
  icon,
  title,
  description,
  action,
  secondaryAction,
  className,
  animationSize = 120,
  card = false,
  compact = false,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center text-center",
        compact ? "py-8 px-4" : "py-16 px-6",
        card && "rounded-lg border border-border bg-card",
        "animate-fade-in",
        className
      )}
    >
      {/* Animation / Icon */}
      <div className={cn("mb-4", compact && "mb-3")}>
        {preset ? (
          <LottiePlayer
            preset={preset}
            size={compact ? Math.round(animationSize * 0.7) : animationSize}
            className="opacity-90"
          />
        ) : icon ? (
          <div className="rounded-full bg-muted p-4">
            {icon}
          </div>
        ) : (
          <div className="rounded-full bg-muted p-4">
            <InboxIcon />
          </div>
        )}
      </div>

      {/* Text */}
      <h3 className={cn(
        "font-semibold text-foreground",
        compact ? "text-sm" : "text-base"
      )}>
        {title}
      </h3>

      {description && (
        <p className={cn(
          "mt-1.5 text-muted-foreground max-w-sm",
          compact ? "text-xs" : "text-sm"
        )}>
          {description}
        </p>
      )}

      {/* Actions */}
      {(action || secondaryAction) && (
        <div className={cn(
          "flex flex-wrap items-center justify-center gap-3",
          compact ? "mt-4" : "mt-6"
        )}>
          {action}
          {secondaryAction}
        </div>
      )}
    </div>
  );
}

// ── Preset empty states ───────────────────────────────────────────────────────

export function NoDataEmptyState({
  onUpload,
  className,
}: {
  onUpload?: () => void;
  className?: string;
}) {
  return (
    <EmptyState
      preset="empty"
      title="Henüz veri yok"
      description="Finansal belgenizi yükleyin — banka ekstresi, Excel veya CSV formatında."
      action={
        onUpload ? (
          <button
            onClick={onUpload}
            className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 transition-state press-feedback"
          >
            Veri Yükle
          </button>
        ) : undefined
      }
      className={className}
    />
  );
}

export function NoResultsEmptyState({
  query,
  onClear,
  className,
}: {
  query?: string;
  onClear?: () => void;
  className?: string;
}) {
  return (
    <EmptyState
      preset="empty"
      title="Sonuç bulunamadı"
      description={
        query
          ? `"${query}" için eşleşen kayıt yok. Filtrelerinizi değiştirmeyi deneyin.`
          : "Arama kriterlerinizle eşleşen kayıt yok."
      }
      action={
        onClear ? (
          <button
            onClick={onClear}
            className="rounded-lg border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted transition-state"
          >
            Filtreleri Temizle
          </button>
        ) : undefined
      }
      compact
      className={className}
    />
  );
}

export function AnalysisEmptyState({
  agentName,
  className,
}: {
  agentName?: string;
  className?: string;
}) {
  return (
    <EmptyState
      preset="thinking"
      animationSize={80}
      title={agentName ? `${agentName} analizi yapılmadı` : "Analiz henüz çalışmadı"}
      description="Sol formu doldurun ve analizi başlatın."
      compact
      className={className}
    />
  );
}

// ── Ek domain-specific empty state'ler ───────────────────────────────────────

export function NoAlertsEmptyState({ className }: { className?: string }) {
  return (
    <EmptyState
      icon={
        <svg width="40" height="40" viewBox="0 0 40 40" fill="none" aria-hidden="true" className="text-emerald-400/60">
          <circle cx="20" cy="20" r="16" stroke="currentColor" strokeWidth="1.5" fill="currentColor" fillOpacity="0.08"/>
          <path d="M14 20l4 4 8-8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      }
      title="Aktif alert yok"
      description="Tüm KRI'lar normal sınırlar içinde. Proaktif tarama çalışıyor."
      compact
      className={className}
    />
  );
}

export function NoJobsEmptyState({
  onUpload,
  className,
}: { onUpload?: () => void; className?: string }) {
  return (
    <EmptyState
      icon={
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none" aria-hidden="true" className="text-muted-foreground/40">
          <rect x="8" y="4" width="24" height="32" rx="3" stroke="currentColor" strokeWidth="1.5" fill="currentColor" fillOpacity="0.04"/>
          <path d="M14 14h12M14 20h8M14 26h6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          <circle cx="34" cy="34" r="8" fill="currentColor" fillOpacity="0.1" stroke="currentColor" strokeWidth="1.5"/>
          <path d="M31 34h6M34 31v6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      }
      title="Henüz analiz yapılmadı"
      description="İlk finansal belgenizi yükleyin. Banka ekstresi, Excel veya CSV formatında desteklenir."
      action={
        onUpload ? (
          <button
            onClick={onUpload}
            className="flex items-center gap-2 rounded-lg bg-primary px-5 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 transition-opacity"
          >
            İlk Analizi Başlat →
          </button>
        ) : undefined
      }
      className={className}
    />
  );
}

export function NoChatHistoryEmptyState({ className }: { className?: string }) {
  const questions = [
    "Nakit pisti ne kadar?",
    "En büyük gider kalemim nedir?",
    "Bu çeyrek büyüme trendi nasıl?",
  ];
  return (
    <div className={cn("flex flex-col items-center gap-4 py-12 px-6 text-center", className)}>
      <div className="rounded-full bg-primary/10 p-4">
        <svg width="32" height="32" viewBox="0 0 32 32" fill="none" aria-hidden="true" className="text-primary">
          <path d="M4 8a4 4 0 014-4h16a4 4 0 014 4v12a4 4 0 01-4 4H12l-6 4v-4H8a4 4 0 01-4-4V8z" stroke="currentColor" strokeWidth="1.5" fill="currentColor" fillOpacity="0.1"/>
          <path d="M10 13h12M10 18h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      </div>
      <div>
        <p className="font-semibold text-sm">CFO Asistanı hazır</p>
        <p className="mt-1 text-xs text-muted-foreground">Şirket verileriniz üzerinde Türkçe soru sorun</p>
      </div>
      <div className="flex flex-wrap gap-2 justify-center max-w-xs">
        {questions.map((q) => (
          <span key={q} className="rounded-full border border-border bg-muted/50 px-3 py-1 text-xs text-muted-foreground">
            {q}
          </span>
        ))}
      </div>
    </div>
  );
}

export function NoIntegrationsEmptyState({
  onSetup,
  className,
}: { onSetup?: () => void; className?: string }) {
  return (
    <EmptyState
      icon={
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none" aria-hidden="true" className="text-muted-foreground/40">
          <circle cx="12" cy="24" r="7" stroke="currentColor" strokeWidth="1.5" fill="currentColor" fillOpacity="0.04"/>
          <circle cx="36" cy="24" r="7" stroke="currentColor" strokeWidth="1.5" fill="currentColor" fillOpacity="0.04"/>
          <path d="M19 24h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeDasharray="3 2"/>
        </svg>
      }
      title="Entegrasyon bağlı değil"
      description="Paraşüt, Logo Tiger veya banka hesabınızı bağlayarak otomatik veri çekme yapın."
      action={
        onSetup ? (
          <button
            onClick={onSetup}
            className="rounded-lg border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted transition-colors"
          >
            Entegrasyon Kur
          </button>
        ) : undefined
      }
      compact
      className={className}
    />
  );
}
