"use client";
/**
 * NLQueryPanel — Natural language "what-if" simulation panel.
 *
 * Sends plain-language questions to /advanced/nl-simulate and renders
 * the structured result: answer, extracted params, follow-up suggestions.
 *
 * Used in the Simulation page as the "Doğal Dil" tab.
 */
import { useState, useRef, type FormEvent } from "react";
import {
  Sparkles, Send, RotateCcw, ChevronRight,
  TrendingUp, AlertTriangle, Loader2, CheckCircle2,
} from "lucide-react";
import { useNLQuery, NL_QUERY_SUGGESTIONS } from "@/hooks/useNLQuery";
import { BaselineSourceBadge } from "@/components/ui/baseline-source-badge";
import { cn } from "@/lib/utils";

// ── Confidence badge ──────────────────────────────────────────────────────────

function ConfidenceBadge({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color =
    pct >= 80 ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" :
    pct >= 60 ? "text-amber-400 bg-amber-500/10 border-amber-500/20" :
                "text-muted-foreground bg-muted border-border";
  return (
    <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-medium", color)}>
      %{pct} güven
    </span>
  );
}

// ── Extracted params display ──────────────────────────────────────────────────

function ExtractedParams({ params }: { params: Record<string, unknown> }) {
  const entries = Object.entries(params).filter(([, v]) => v !== null && v !== undefined);
  if (!entries.length) return null;

  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2.5">
      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Çıkarılan Parametreler
      </p>
      <div className="flex flex-wrap gap-1.5">
        {entries.map(([k, v]) => (
          <span
            key={k}
            className="rounded-md bg-primary/10 px-2 py-0.5 text-xs text-primary"
          >
            <span className="text-muted-foreground">{k}:</span>{" "}
            {typeof v === "object" ? JSON.stringify(v) : String(v)}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Result card ───────────────────────────────────────────────────────────────

function ResultCard({
  result,
  query,
  onFollowUp,
}: {
  result: NonNullable<ReturnType<typeof useNLQuery>["result"]>;
  query: string;
  onFollowUp: (q: string) => void;
}) {
  if (!result.ok && result.error) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/8 px-4 py-3">
        <div className="flex items-center gap-2 text-destructive">
          <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
          <p className="text-sm font-medium">Simülasyon başarısız</p>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{result.error}</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" aria-hidden="true" />
          <p className="truncate text-xs text-muted-foreground">{query}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {result.simulation_type && (
            <span className="rounded-md bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground capitalize">
              {result.simulation_type.replace(/_/g, " ")}
            </span>
          )}
          <ConfidenceBadge score={result.intent_confidence} />
        </div>
      </div>

      {/* Answer */}
      <div className="rounded-lg border border-primary/20 bg-primary/5 px-4 py-3">
        <div className="flex items-center gap-1.5 mb-2">
          <TrendingUp className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
          <p className="text-xs font-semibold text-primary">AI Yanıtı</p>
        </div>
        <p className="text-sm leading-relaxed text-foreground">{result.answer}</p>
      </div>

      {/* Extracted params */}
      {Object.keys(result.extracted_params).length > 0 && (
        <ExtractedParams params={result.extracted_params} />
      )}

      {/* Follow-up suggestions */}
      {result.follow_up_questions.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Sonraki Sorular
          </p>
          {result.follow_up_questions.map((q, i) => (
            <button
              key={i}
              onClick={() => onFollowUp(q)}
              className={cn(
                "flex w-full items-center gap-2 rounded-lg border border-border bg-card",
                "px-3 py-2 text-left text-xs text-muted-foreground",
                "transition-colors hover:border-primary/20 hover:bg-primary/5 hover:text-foreground"
              )}
            >
              <ChevronRight className="h-3 w-3 shrink-0 text-primary" aria-hidden="true" />
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Suggestion chips ──────────────────────────────────────────────────────────

function SuggestionChips({ onSelect }: { onSelect: (q: string) => void }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Doğal dilde herhangi bir iş sorusu sorun — AI otomatik simüle eder.
      </p>
      <div className="space-y-2">
        {NL_QUERY_SUGGESTIONS.map((group) => (
          <div key={group.category}>
            <button
              onClick={() => setExpanded(expanded === group.category ? null : group.category)}
              className="flex items-center gap-2 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
              <span aria-hidden="true">{group.icon}</span>
              {group.category}
              <ChevronRight
                className={cn(
                  "h-3 w-3 transition-transform",
                  expanded === group.category && "rotate-90"
                )}
                aria-hidden="true"
              />
            </button>

            {expanded === group.category && (
              <div className="mt-1.5 ml-5 space-y-1">
                {group.queries.map((q) => (
                  <button
                    key={q}
                    onClick={() => onSelect(q)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-lg border border-border bg-card",
                      "px-3 py-2 text-left text-xs text-muted-foreground",
                      "transition-colors hover:border-primary/20 hover:bg-primary/5 hover:text-foreground"
                    )}
                  >
                    <ChevronRight className="h-2.5 w-2.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                    {q}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

interface NLQueryPanelProps {
  jobId?: string | null;
  orgId?: string | null;
  baselineSource?: string;
  goldenPathReady?: boolean;
}

export function NLQueryPanel({
  jobId,
  baselineSource,
  goldenPathReady,
}: NLQueryPanelProps) {
  const { ask, reset, result, isLoading, error, lastQuery } = useNLQuery();
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!input.trim() || isLoading) return;
    const q = input.trim();
    setInput("");
    await ask(q, jobId);
  }

  function handleSuggestion(q: string) {
    setInput(q);
    inputRef.current?.focus();
  }

  function handleFollowUp(q: string) {
    setInput(q);
    inputRef.current?.focus();
  }

  function handleReset() {
    reset();
    setInput("");
    inputRef.current?.focus();
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 min-w-0">
          <Sparkles className="h-4 w-4 text-primary shrink-0" aria-hidden="true" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold">Doğal Dil Simülasyonu</h3>
              {baselineSource && <BaselineSourceBadge source={baselineSource} />}
            </div>
            <p className="text-xs text-muted-foreground">
              İş sorunuzu yazın — AI senaryoyu otomatik çalıştırır
            </p>
            {goldenPathReady && (
              <p className="text-[10px] text-emerald-400 mt-0.5">
                Canonical baseline active — NL simülasyon gerçek metrikleri kullanır.
              </p>
            )}
          </div>
        </div>
        {result && (
          <button
            onClick={handleReset}
            className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
            aria-label="Sonucu sıfırla"
          >
            <RotateCcw className="h-3 w-3" aria-hidden="true" />
            Sıfırla
          </button>
        )}
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="space-y-2">
        <div className="relative">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSubmit(e as unknown as FormEvent);
              }
            }}
            placeholder="Örn: '5 mühendis işe alırsam 12 ayda net etkisi ne olur?'"
            rows={3}
            disabled={isLoading}
            aria-label="Simülasyon sorusu"
            className={cn(
              "w-full resize-none rounded-lg border border-border bg-card",
              "px-4 py-3 pr-12 text-sm text-foreground",
              "placeholder:text-muted-foreground/50",
              "focus:outline-none focus:ring-2 focus:ring-primary",
              "disabled:opacity-50"
            )}
          />
          <button
            type="submit"
            disabled={!input.trim() || isLoading}
            aria-label="Simülasyonu çalıştır"
            className={cn(
              "absolute right-2.5 bottom-2.5 flex h-8 w-8 items-center justify-center",
              "rounded-md bg-primary text-primary-foreground",
              "transition-opacity hover:opacity-90 disabled:opacity-40"
            )}
          >
            {isLoading
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              : <Send className="h-3.5 w-3.5" aria-hidden="true" />
            }
          </button>
        </div>
        <p className="text-[10px] text-muted-foreground">
          Enter ile gönder · Shift+Enter yeni satır
        </p>
      </form>

      {/* Loading state */}
      {isLoading && (
        <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-3">
          <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />
          <span className="text-sm text-muted-foreground">
            AI simülasyonu çalıştırıyor…
          </span>
        </div>
      )}

      {/* Error state */}
      {error && !isLoading && !result && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/8 px-4 py-3">
          <div className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
            <p className="text-sm">{error}</p>
          </div>
        </div>
      )}

      {/* Result */}
      {result && !isLoading && (
        <ResultCard
          result={result}
          query={lastQuery ?? ""}
          onFollowUp={handleFollowUp}
        />
      )}

      {/* Suggestions — only when no result */}
      {!result && !isLoading && (
        <SuggestionChips onSelect={handleSuggestion} />
      )}
    </div>
  );
}
