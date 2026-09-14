"use client";
/**
 * ProactiveActionCards — "Şimdi Yap" aksiyon kartları.
 *
 * Analiz tamamlandıktan sonra her agent sayfasında gösterilir.
 * Her kart: aksiyon başlığı + tahmini etki + efor + chat'e yönlendirme.
 *
 * Usage:
 *   <ProactiveActionCards
 *     actions={ctoResult.cto_summary?.quick_wins}
 *     agent="cto"
 *     agentLabel="CTO"
 *   />
 */

import { useState } from "react";
import { Zap, ArrowRight, Clock, TrendingUp, MessageSquare, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { AgentChatPanel, type AgentFilter } from "./agent-chat-panel";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ActionItem {
  action: string;
  estimated_impact: string;
  effort?: "low" | "medium" | "high";
  urgency?: "immediate" | "this_week" | "this_month" | "normal";
  domain?: string;
}

interface ProactiveActionCardsProps {
  /** Quick win / action items from agent summary */
  actions: ActionItem[] | null | undefined;
  /** Agent filter for the chat panel */
  agent?: AgentFilter;
  /** Display label */
  agentLabel?: string;
  /** Max items to show before collapse (default: 3) */
  maxVisible?: number;
  className?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function effortStyle(effort: ActionItem["effort"]) {
  switch (effort) {
    case "low":    return { cls: "bg-emerald-500/15 text-emerald-400 border-emerald-500/25", label: "Kolay" };
    case "medium": return { cls: "bg-amber-500/15 text-amber-400 border-amber-500/25",     label: "Orta" };
    case "high":   return { cls: "bg-red-500/15 text-red-400 border-red-500/25",           label: "Zor" };
    default:       return { cls: "bg-muted text-muted-foreground border-border",            label: "—" };
  }
}

function urgencyStyle(urgency: ActionItem["urgency"]) {
  switch (urgency) {
    case "immediate":  return { cls: "text-red-400",     label: "Hemen" };
    case "this_week":  return { cls: "text-amber-400",   label: "Bu hafta" };
    case "this_month": return { cls: "text-blue-400",    label: "Bu ay" };
    default:           return { cls: "text-muted-foreground", label: "Normal" };
  }
}

// ── Single action card ────────────────────────────────────────────────────────

function ActionCard({
  item,
  index,
  onAskChat,
}: {
  item: ActionItem;
  index: number;
  onAskChat: (question: string) => void;
}) {
  const effort  = effortStyle(item.effort);
  const urgency = urgencyStyle(item.urgency);

  return (
    <div
      className={cn(
        "group rounded-lg border border-border bg-card p-4",
        "hover-lift transition-lift",
        "animate-slide-up"
      )}
      style={{ animationDelay: `${index * 60}ms` }}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-3 mb-2.5">
        <div className="flex items-start gap-2.5 flex-1 min-w-0">
          {/* Number badge */}
          <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[10px] font-bold text-primary">
            {index + 1}
          </span>
          <p className="text-sm font-semibold leading-snug">{item.action}</p>
        </div>

        {/* Effort badge */}
        {item.effort && (
          <span className={cn("shrink-0 rounded border px-2 py-0.5 text-[10px] font-semibold", effort.cls)}>
            {effort.label}
          </span>
        )}
      </div>

      {/* Impact */}
      {item.estimated_impact && (
        <div className="mb-3 flex items-center gap-1.5 text-xs text-muted-foreground">
          <TrendingUp className="h-3 w-3 shrink-0 text-emerald-400" aria-hidden="true" />
          <span>{item.estimated_impact}</span>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between gap-2">
        {/* Urgency */}
        {item.urgency && item.urgency !== "normal" && (
          <div className="flex items-center gap-1 text-[10px]">
            <Clock className={cn("h-3 w-3 shrink-0", urgency.cls)} aria-hidden="true" />
            <span className={urgency.cls}>{urgency.label}</span>
          </div>
        )}
        {(!item.urgency || item.urgency === "normal") && (
          <span />
        )}

        {/* Ask AI button */}
        <button
          onClick={() => onAskChat(`${item.action} — bunu nasıl uygulayabilirim?`)}
          className={cn(
            "flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-[11px] text-muted-foreground",
            "hover:border-primary/40 hover:bg-primary/5 hover:text-primary transition-state",
            "opacity-0 group-hover:opacity-100 transition-opacity duration-150"
          )}
        >
          <MessageSquare className="h-3 w-3" aria-hidden="true" />
          AI ile uygula
          <ArrowRight className="h-3 w-3" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function ProactiveActionCards({
  actions,
  agent = "all",
  agentLabel = "Agent",
  maxVisible = 3,
  className,
}: ProactiveActionCardsProps) {
  const [expanded, setExpanded] = useState(false);
  const [chatQuestion, setChatQuestion] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);

  if (!actions || actions.length === 0) return null;

  const visible = expanded ? actions : actions.slice(0, maxVisible);
  const hasMore = actions.length > maxVisible;

  function handleAskChat(question: string) {
    setChatQuestion(question);
    setChatOpen(true);
  }

  return (
    <div className={cn("space-y-3", className)}>
      {/* Header */}
      <div className="flex items-center gap-2">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/15">
          <Zap className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
        </div>
        <h3 className="text-sm font-semibold">Önerilen Aksiyonlar</h3>
        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
          {actions.length} öneri
        </span>
        <span className="ml-1 text-[10px] text-muted-foreground">— AI tarafından önceliklendirildi</span>
      </div>

      {/* Action cards grid */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {visible.map((item, i) => (
          <ActionCard
            key={i}
            item={item}
            index={i}
            onAskChat={handleAskChat}
          />
        ))}
      </div>

      {/* Show more / less */}
      {hasMore && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-state"
        >
          {expanded ? (
            <><ChevronUp className="h-3.5 w-3.5" aria-hidden="true" />Daha az göster</>
          ) : (
            <><ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />{actions.length - maxVisible} aksiyon daha</>
          )}
        </button>
      )}

      {/* Chat CTA when all actions are viewed */}
      {(expanded || !hasMore) && actions.length > 0 && (
        <div className="rounded-lg border border-dashed border-primary/30 bg-primary/5 px-4 py-3 flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium">Aksiyonları nasıl uygularsınız?</p>
            <p className="text-xs text-muted-foreground">AI danışmanınız adım adım rehberlik edebilir.</p>
          </div>
          <button
            onClick={() => handleAskChat(`${agentLabel} önerilerini nasıl uygulayabilirim? Öncelik sırasını söyle.`)}
            className={cn(
              "flex shrink-0 items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground",
              "hover:opacity-90 transition-state press-feedback"
            )}
          >
            <MessageSquare className="h-4 w-4" aria-hidden="true" />
            AI ile konuş
          </button>
        </div>
      )}

      {/* Inline chat panel trigger — opens global panel with pre-filled question */}
      {chatOpen && chatQuestion && (
        <AgentChatPanel
          agentFilter={agent}
          agentLabel={agentLabel}
          suggestions={[chatQuestion]}
        />
      )}
    </div>
  );
}
