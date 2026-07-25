"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import { Star, X, Send, Loader2, CheckCircle, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface FeedbackWidgetProps {
  jobId?: string;
  pageContext?: string;
  onClose?: () => void;
}

function StarRating({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  const [hover, setHover] = useState(0);
  return (
    <div className="flex items-center gap-3">
      <span className="w-32 shrink-0 text-xs text-muted-foreground">{label}</span>
      <div className="flex gap-0.5">
        {[1, 2, 3, 4, 5].map((star) => (
          <button
            key={star}
            type="button"
            onMouseEnter={() => setHover(star)}
            onMouseLeave={() => setHover(0)}
            onClick={() => onChange(star)}
            className="p-0.5 transition-colors"
            aria-label={`${label}: ${star} yıldız`}
          >
            <Star
              className={cn(
                "h-4 w-4",
                (hover || value) >= star
                  ? "fill-amber-400 text-amber-400"
                  : "text-muted-foreground"
              )}
            />
          </button>
        ))}
      </div>
      {value > 0 && (
        <span className="text-xs text-muted-foreground tabular-nums">{value}/5</span>
      )}
    </div>
  );
}

function NPSSlider({ value, onChange }: { value: number | null; onChange: (v: number) => void }) {
  return (
    <div>
      <p className="mb-2 text-xs text-muted-foreground">
        Bu platformu bir arkadaşınıza veya meslektaşınıza ne kadar tavsiye edersiniz?
      </p>
      <div className="flex gap-1">
        {Array.from({ length: 11 }, (_, i) => i).map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => onChange(n)}
            className={cn(
              "flex h-8 w-8 items-center justify-center rounded text-xs font-medium transition-colors",
              value === n
                ? n >= 9
                  ? "bg-emerald-500 text-white"
                  : n >= 7
                  ? "bg-blue-500 text-white"
                  : "bg-destructive text-white"
                : "border border-border text-muted-foreground hover:border-primary/40 hover:text-foreground"
            )}
            aria-label={`NPS: ${n}`}
          >
            {n}
          </button>
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
        <span>Kesinlikle önermem</span>
        <span>Kesinlikle öneririm</span>
      </div>
    </div>
  );
}

export function FeedbackWidget({ jobId, pageContext = "dashboard", onClose }: FeedbackWidgetProps) {
  const { data: session } = useSession();
  const [expanded, setExpanded] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [nps, setNps] = useState<number | null>(null);
  const [analysisRating, setAnalysisRating] = useState(0);
  const [accuracyRating, setAccuracyRating] = useState(0);
  const [usefulnessRating, setUsefulnessRating] = useState(0);
  const [speedRating, setSpeedRating] = useState(0);
  const [comment, setComment] = useState("");
  const [benefit, setBenefit] = useState("");
  const [gap, setGap] = useState("");

  const accessToken = (session as any)?.accessToken as string | undefined;

  async function handleSubmit() {
    if (nps === null && analysisRating === 0 && !comment) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/pilot/feedback`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
        body: JSON.stringify({
          job_id: jobId ?? null,
          nps_score: nps,
          analysis_rating: analysisRating || null,
          accuracy_rating: accuracyRating || null,
          usefulness_rating: usefulnessRating || null,
          speed_rating: speedRating || null,
          comment: comment || null,
          biggest_benefit: benefit || null,
          biggest_gap: gap || null,
          page_context: pageContext,
        }),
      });
      if (!res.ok) throw new Error("Gönderim başarısız.");
      setSubmitted(true);
    } catch {
      setError("Feedback gönderilemedi. Lütfen tekrar deneyin.");
    } finally {
      setLoading(false);
    }
  }

  // Submitted state
  if (submitted) {
    return (
      <div className="rounded-xl border border-emerald-500/20 bg-emerald-950/10 p-4">
        <div className="flex items-start gap-3">
          <CheckCircle className="mt-0.5 h-5 w-5 shrink-0 text-emerald-400" />
          <div className="flex-1">
            <p className="text-sm font-medium text-emerald-400">Teşekkürler!</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Geri bildiriminiz ürünü iyileştirmemize yardımcı olacak.
            </p>
          </div>
          {onClose && (
            <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-card">
      {/* Header */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
        aria-expanded={expanded}
      >
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10">
          <Star className="h-4 w-4 text-primary" aria-hidden="true" />
        </div>
        <div className="flex-1">
          <p className="text-sm font-medium">Bu analiz nasıldı?</p>
          <p className="text-xs text-muted-foreground">
            1 dakika içinde geri bildirim bırakın
          </p>
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        )}
      </button>

      {/* Expanded form */}
      {expanded && (
        <div className="border-t border-border px-4 pb-4 pt-3 space-y-4">
          {/* Quick star rating */}
          <div className="space-y-2.5">
            <StarRating label="Genel analiz" value={analysisRating} onChange={setAnalysisRating} />
            <StarRating label="Doğruluk" value={accuracyRating} onChange={setAccuracyRating} />
            <StarRating label="Kullanışlılık" value={usefulnessRating} onChange={setUsefulnessRating} />
            <StarRating label="Hız" value={speedRating} onChange={setSpeedRating} />
          </div>

          {/* NPS */}
          <NPSSlider value={nps} onChange={setNps} />

          {/* Open text */}
          <div className="space-y-2">
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Bu analiz size nasıl yardımcı oldu? (isteğe bağlı)"
              rows={2}
              className={cn(
                "w-full rounded-md border border-border bg-background px-3 py-2 text-sm",
                "placeholder:text-muted-foreground resize-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              )}
            />
            <textarea
              value={gap}
              onChange={(e) => setGap(e.target.value)}
              placeholder="Eksik gördüğünüz bir şey var mı? (isteğe bağlı)"
              rows={2}
              className={cn(
                "w-full rounded-md border border-border bg-background px-3 py-2 text-sm",
                "placeholder:text-muted-foreground resize-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              )}
            />
          </div>

          {error && (
            <p className="text-xs text-destructive">{error}</p>
          )}

          <div className="flex items-center gap-2">
            <button
              onClick={handleSubmit}
              disabled={loading || (nps === null && analysisRating === 0 && !comment)}
              className={cn(
                "flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-xs font-medium text-primary-foreground",
                "transition-opacity hover:opacity-90 disabled:pointer-events-none disabled:opacity-50"
              )}
            >
              {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
              Gönder
            </button>
            <button
              onClick={() => setExpanded(false)}
              className="text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              Daha sonra
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
