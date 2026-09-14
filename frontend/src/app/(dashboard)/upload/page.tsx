"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Upload, AlertTriangle, CheckCircle2, XCircle,
  RefreshCw, ArrowRight, ChevronDown, ChevronUp, Info, Files, Building2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  validateAndUpload, acceptColumnMapping,
  type ValidationResult, type ColumnInfo,
} from "@/lib/api/data_quality";
import { MultiBatchUpload } from "@/components/upload/MultiBatchUpload";
import { POST_UPLOAD_ROUTE } from "@/lib/routes";
import { apiClient } from "@/lib/api/client";

// ── Health score helpers ──────────────────────────────────────────────────────

function healthColor(score: number): string {
  if (score >= 90) return "text-emerald-400";
  if (score >= 75) return "text-emerald-400";
  if (score >= 55) return "text-amber-400";
  if (score >= 35) return "text-orange-400";
  return "text-red-400";
}

function healthBg(score: number): string {
  if (score >= 90) return "bg-emerald-500/15";
  if (score >= 75) return "bg-emerald-500/10";
  if (score >= 55) return "bg-amber-500/10";
  if (score >= 35) return "bg-orange-500/10";
  return "bg-red-500/10";
}

function healthBorder(score: number): string {
  if (score >= 75) return "border-emerald-500/30";
  if (score >= 55) return "border-amber-500/30";
  if (score >= 35) return "border-orange-500/30";
  return "border-red-500/30";
}

function healthLabel(label: string): string {
  const map: Record<string, string> = {
    excellent: "Mükemmel",
    good: "İyi",
    fair: "Orta",
    poor: "Zayıf",
    critical: "Kritik",
  };
  return map[label] ?? label;
}

// ── Health Score Ring ─────────────────────────────────────────────────────────

function HealthScoreRing({ score, label }: { score: number; label: string }) {
  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="96" height="96" viewBox="0 0 96 96" aria-hidden="true">
        <circle cx="48" cy="48" r={radius} fill="none" strokeWidth="8" className="stroke-border" />
        <circle
          cx="48" cy="48" r={radius} fill="none" strokeWidth="8"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform="rotate(-90 48 48)"
          className={cn(
            "transition-all duration-700",
            score >= 75 ? "stroke-emerald-400" :
            score >= 55 ? "stroke-amber-400" :
            score >= 35 ? "stroke-orange-400" : "stroke-red-400"
          )}
        />
        <text x="48" y="44" textAnchor="middle" className="fill-foreground text-xl font-bold" fontSize="20">
          {score}
        </text>
        <text x="48" y="60" textAnchor="middle" className="fill-muted-foreground" fontSize="10">
          /100
        </text>
      </svg>
      <span className={cn("text-sm font-semibold", healthColor(score))}>
        {healthLabel(label)}
      </span>
    </div>
  );
}

// ── Column mapping row ────────────────────────────────────────────────────────

const SYSTEM_FIELDS = [
  { value: "",             label: "— Eşleştirme yok —" },
  { value: "date",         label: "Tarih (zorunlu)" },
  { value: "amount",       label: "Tutar (zorunlu)" },
  { value: "description",  label: "Açıklama" },
  { value: "category",     label: "Kategori" },
  { value: "reference",    label: "Referans No" },
];

function ColumnMappingRow({
  col,
  mappedField,
  onChange,
}: {
  col: ColumnInfo;
  mappedField: string;
  onChange: (field: string) => void;
}) {
  const typeIcon =
    col.detected_type === "date" ? "📅" :
    col.detected_type === "amount" ? "💰" :
    col.detected_type === "text" ? "📝" : "🔢";

  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-card px-3 py-2.5">
      {/* Column name */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span aria-hidden="true">{typeIcon}</span>
          <span className="truncate text-sm font-medium">{col.raw_name}</span>
          {col.issues.length > 0 && (
            <span title={col.issues.join("; ")}>
              <AlertTriangle className="h-3.5 w-3.5 text-amber-400" aria-hidden="true" />
            </span>
          )}
        </div>
        <p className="mt-0.5 text-[11px] text-muted-foreground">
          {col.null_pct > 0 && `%${col.null_pct.toFixed(0)} boş · `}
          {col.sample_values.slice(0, 2).join(", ")}
          {col.sample_values.length > 2 && "…"}
        </p>
      </div>

      {/* Arrow */}
      <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />

      {/* System field select */}
      <select
        value={mappedField}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "h-8 rounded-md border text-sm",
          "bg-muted/30 px-2 pr-7",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          mappedField ? "border-primary/30 text-foreground" : "border-border text-muted-foreground"
        )}
      >
        {SYSTEM_FIELDS.map((f) => (
          <option key={f.value} value={f.value}>{f.label}</option>
        ))}
      </select>
    </div>
  );
}

// ── Issue list ────────────────────────────────────────────────────────────────

function IssueList({ validation }: { validation: ValidationResult }) {
  const [expanded, setExpanded] = useState(false);
  const errors = validation.row_issues.filter((i) => i.severity === "error");
  const warnings = validation.row_issues.filter((i) => i.severity === "warning");
  const infos = validation.row_issues.filter((i) => i.severity === "info");

  const visible = expanded ? validation.row_issues : validation.row_issues.slice(0, 5);

  if (validation.row_issues.length === 0) return null;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        {errors.length > 0 && (
          <span className="flex items-center gap-1 text-red-400">
            <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
            {errors.length} hata
          </span>
        )}
        {warnings.length > 0 && (
          <span className="flex items-center gap-1 text-amber-400">
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
            {warnings.length} uyarı
          </span>
        )}
        {infos.length > 0 && (
          <span className="flex items-center gap-1 text-blue-400">
            <Info className="h-3.5 w-3.5" aria-hidden="true" />
            {infos.length} bilgi
          </span>
        )}
      </div>

      <div className="space-y-1">
        {visible.map((issue, i) => (
          <div
            key={i}
            className={cn(
              "flex items-start gap-2 rounded-md px-3 py-2 text-xs",
              issue.severity === "error" ? "bg-red-500/8 text-red-300" :
              issue.severity === "warning" ? "bg-amber-500/8 text-amber-300" :
              "bg-blue-500/8 text-blue-300"
            )}
          >
            <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
              {issue.row > 0 ? `R${issue.row}` : "—"}
            </span>
            <span className="leading-relaxed">{issue.message}</span>
          </div>
        ))}
      </div>

      {validation.row_issues.length > 5 && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-1 text-xs text-primary hover:opacity-80"
        >
          {expanded ? (
            <><ChevronUp className="h-3.5 w-3.5" aria-hidden="true" /> Daha az göster</>
          ) : (
            <><ChevronDown className="h-3.5 w-3.5" aria-hidden="true" /> {validation.row_issues.length - 5} tane daha göster</>
          )}
        </button>
      )}
    </div>
  );
}

// ── Upload drop zone ──────────────────────────────────────────────────────────

function DropZone({
  onFile,
  loading,
}: {
  onFile: (file: File) => void;
  loading: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) onFile(file);
  }

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="CSV dosyası seçmek için tıklayın veya sürükleyin"
      onClick={() => inputRef.current?.click()}
      onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={cn(
        "flex flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed p-12 transition-colors cursor-pointer",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        dragging ? "border-primary bg-primary/5" : "border-border hover:border-primary/40 hover:bg-muted/30",
        loading && "pointer-events-none opacity-60"
      )}
    >
      <div className={cn(
        "flex h-14 w-14 items-center justify-center rounded-2xl transition-colors",
        dragging ? "bg-primary/20" : "bg-muted"
      )}>
        {loading
          ? <RefreshCw className="h-6 w-6 animate-spin text-primary" aria-hidden="true" />
          : <Upload className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
        }
      </div>

      <div className="text-center">
        <p className="font-semibold">
          {loading ? "Analiz ediliyor…" : "CSV dosyasını sürükleyin veya tıklayın"}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          Logo Tiger · Paraşüt · Akbank · Garanti · GİB e-Fatura XML · Genel CSV/Excel
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Maksimum 10 MB · .csv, .xlsx, .xls, .pdf, .xml
        </p>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".csv,.xlsx,.xls,.pdf,.xml,.txt,.tsv"
        className="sr-only"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
        }}
      />
    </div>
  );
}

// Where a finished upload goes. This used to be "/", which was the dashboard
// until a marketing landing page took that route — after which someone who had
// just uploaded their financials was sent to a page inviting them to sign up,
// with their job id sitting unread in the query string. /pnl is the route the
// nav labels "Dashboard" and one of the pages that actually reads ?job=.

// ── Main upload page ──────────────────────────────────────────────────────────

type Phase = "idle" | "validating" | "review" | "uploading" | "done" | "error";

export default function UploadPage() {
  const router = useRouter();
  // Set when an accountant arrives from the client list ("/upload?client=…").
  // Every upload path has to carry it or the file lands unattributed and the
  // portal cannot say whose work is waiting.
  const clientId = useSearchParams().get("client");
  const [clientName, setClientName] = useState<string | null>(null);

  useEffect(() => {
    if (!clientId) return;
    let live = true;
    apiClient
      .get<{ clients: Array<{ id: string; firma_adi: string }> }>("/smmm/clients")
      .then((res) => {
        const match = res.data.clients?.find((c) => c.id === clientId);
        if (live) setClientName(match?.firma_adi ?? null);
      })
      .catch(() => {
        /* The banner falls back to "seçili müşteri"; the upload still carries
           the id, which is what actually matters. */
      });
    return () => { live = false; };
  }, [clientId]);

  const [phase, setPhase] = useState<Phase>("idle");
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [columnMapping, setColumnMapping] = useState<Record<string, string>>({});
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Auto-redirect to dashboard once job is ready
  useEffect(() => {
    if (phase === "done" && jobId) {
      // Mark tour as pending so dashboard auto-starts the tour on first upload
      import("@/components/ui/product-tour").then(({ markTourPending }) => {
        markTourPending();
      });

      // Small delay so the user sees the success state briefly
      const t = setTimeout(() => {
        router.push(`${POST_UPLOAD_ROUTE}?job=${jobId}`);
      }, 1200);
      return () => clearTimeout(t);
    }
  }, [phase, jobId, router]);

  // Process file: validate + optionally start analysis
  const handleFile = useCallback(async (file: File) => {
    setSelectedFile(file);
    setPhase("validating");
    setErrorMsg(null);
    setValidation(null);

    try {
      const result = await validateAndUpload(file, { minScore: 40, clientId });

      if (result.validation) {
        setValidation(result.validation);
        // Initialize mapping from auto-detected
        setColumnMapping(result.validation.column_mapping);
      }

      if (result.started && result.job_id) {
        // High-quality file — auto-started
        setJobId(result.job_id);
        setPhase("done");
      } else {
        // Needs review (low score or mapping issues)
        setPhase("review");
      }
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "Dosya işlenemedi");
      setPhase("error");
    }
    // `clientId` is read inside: without it here, an accountant who switched
    // clients would keep uploading against the previous one.
  }, [clientId]);

  // Force upload despite low score
  async function handleForceUpload() {
    if (!selectedFile) return;
    setPhase("uploading");
    try {
      const result = await validateAndUpload(selectedFile, { force: true, clientId });
      if (result.job_id) {
        setJobId(result.job_id);
        setPhase("done");
      } else {
        throw new Error(result.blocked_reason ?? "Yükleme başarısız");
      }
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "Yükleme başarısız");
      setPhase("error");
    }
  }

  // Accept mapping and start analysis
  async function handleAcceptMapping() {
    if (!selectedFile || !validation) return;
    setPhase("uploading");
    try {
      // Read file as base64
      const arrayBuffer = await selectedFile.arrayBuffer();
      const uint8 = new Uint8Array(arrayBuffer);
      let binary = "";
      uint8.forEach((b) => { binary += String.fromCharCode(b); });
      const base64 = btoa(binary);

      const result = await acceptColumnMapping({
        filename: selectedFile.name,
        column_mapping: columnMapping,
        csv_content: base64,
        encoding: validation.encoding,
        client_id: clientId,
      });
      setJobId(result.job_id);
      setPhase("done");
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "Yükleme başarısız");
      setPhase("error");
    }
  }

  // Navigate to results
  function goToDashboard() {
    if (jobId) router.push(`${POST_UPLOAD_ROUTE}?job=${jobId}`);
  }

  const [uploadMode, setUploadMode] = useState<"single" | "batch">("single");

  return (
    <main className="mx-auto max-w-screen-md space-y-6 p-4 sm:p-6 lg:p-8">

      {/* Whose books these are. An accountant working through forty companies
          must not have to remember which tab they are on. */}
      {clientId && (
        <div className="flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm">
          <Building2 className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          <span>
            Bu dosya <strong>{clientName ?? "seçili müşteri"}</strong> için
            yüklenecek.
          </span>
          <Link
            href="/smmm"
            className="ml-auto text-xs text-muted-foreground hover:text-foreground"
          >
            Değiştir
          </Link>
        </div>
      )}

      {/* Mode tabs */}
      <div className="flex items-center gap-1 rounded-lg border border-border bg-card p-1" role="tablist" aria-label="Yükleme modu">
        <button
          role="tab"
          aria-selected={uploadMode === "single"}
          onClick={() => setUploadMode("single")}
          className={cn(
            "flex flex-1 items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
            uploadMode === "single"
              ? "bg-primary/10 text-primary"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          <Upload className="h-4 w-4" aria-hidden="true" />
          Tekli Yükleme
        </button>
        <button
          role="tab"
          aria-selected={uploadMode === "batch"}
          onClick={() => setUploadMode("batch")}
          className={cn(
            "flex flex-1 items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
            uploadMode === "batch"
              ? "bg-primary/10 text-primary"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          <Files className="h-4 w-4" aria-hidden="true" />
          Toplu Yükleme
        </button>
      </div>

      {/* Batch mode panel */}
      {uploadMode === "batch" && (
        <div className="rounded-xl border border-border bg-card p-5">
          <MultiBatchUpload />
        </div>
      )}

      {/* Single mode — existing flow (hidden when batch is active) */}
      {uploadMode === "single" && (<>
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Veri Yükleme</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Muhasebe verilerinizi yükleyin — AI ajanları otomatik analiz başlatır.
        </p>
      </div>

      {/* ── Drop zone ────────────────────────────────────────────────────── */}
      {(phase === "idle" || phase === "error") && (
        <DropZone onFile={handleFile} loading={false} />
      )}

      {phase === "validating" && (
        <DropZone onFile={() => {}} loading={true} />
      )}

      {/* ── Error state ───────────────────────────────────────────────────── */}
      {phase === "error" && errorMsg && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/20 bg-destructive/8 px-4 py-3.5 text-sm text-destructive space-y-2"
        >
          <p className="font-medium">{errorMsg}</p>
          <ul className="text-xs text-destructive/80 space-y-0.5 list-disc list-inside">
            <li>Desteklenen formatlar: <strong>.csv, .txt, .tsv</strong></li>
            <li>Maksimum boyut: <strong>10 MB</strong></li>
            <li>Logo Tiger, Paraşüt, Akbank, Garanti, Ziraat, İş Bankası export'ları destekleniyor</li>
            <li>Sorun devam ederse CSV formatında kayıt ederek tekrar deneyin</li>
          </ul>
        </div>
      )}

      {/* ── Review phase ──────────────────────────────────────────────────── */}
      {phase === "review" && validation && (
        <div className="space-y-5" role="region" aria-label="Veri kalitesi raporu">

          {/* Health score card */}
          <div className={cn(
            "rounded-xl border p-5",
            healthBorder(validation.health_score),
            healthBg(validation.health_score)
          )}>
            <div className="flex items-start gap-5">
              <HealthScoreRing score={validation.health_score} label={validation.health_label} />
              <div className="flex-1 space-y-2">
                <div>
                  <p className="font-semibold">{validation.summary}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Kodlama: {validation.encoding} · Ayraç: {validation.delimiter === "\t" ? "TAB" : `"${validation.delimiter}"`}
                  </p>
                </div>
                <ul className="space-y-1">
                  {validation.recommendations.map((r, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-sm">
                      <span className="mt-0.5 text-xs">•</span>
                      <span>{r}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>

          {/* Issues */}
          <IssueList validation={validation} />

          {/* Column mapping (DQ-2) */}
          <div>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-semibold">Kolon Eşleştirme</h2>
              <p className="text-xs text-muted-foreground">
                Kolonları sistem alanlarıyla eşleştirin
              </p>
            </div>
            <div className="space-y-2">
              {validation.columns.map((col) => (
                <ColumnMappingRow
                  key={col.name}
                  col={col}
                  mappedField={columnMapping[col.mapped_field ?? ""] ? col.mapped_field ?? "" : ""}
                  onChange={(field) => {
                    const newMapping = { ...columnMapping };
                    // Remove old binding for this column
                    Object.keys(newMapping).forEach((k) => {
                      if (newMapping[k] === col.raw_name) delete newMapping[k];
                    });
                    if (field) newMapping[field] = col.raw_name;
                    setColumnMapping(newMapping);
                  }}
                />
              ))}
            </div>
          </div>

          {/* Actions */}
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            {/* Re-upload different file */}
            <button
              onClick={() => { setPhase("idle"); setValidation(null); }}
              className="h-10 rounded-lg border border-border px-5 text-sm font-medium transition-colors hover:bg-muted press-feedback"
            >
              Farklı dosya seç
            </button>

            {/* Force upload even with low score */}
            {validation.health_score < 75 && (
              <button
                onClick={handleForceUpload}
                className="h-10 rounded-lg border border-amber-500/30 bg-amber-500/8 px-5 text-sm font-medium text-amber-300 transition-colors hover:bg-amber-500/15 press-feedback"
              >
                Yine de yükle
              </button>
            )}

            {/* Primary: accept mapping + upload */}
            <button
              onClick={handleAcceptMapping}
              disabled={!columnMapping.date || !columnMapping.amount}
              className={cn(
                "h-10 rounded-lg px-5 text-sm font-semibold transition-opacity press-feedback",
                "bg-primary text-primary-foreground hover:opacity-90",
                "disabled:pointer-events-none disabled:opacity-50"
              )}
            >
              Eşleştirmeyi Onayla & Yükle
              <ArrowRight className="ml-1.5 inline h-4 w-4" aria-hidden="true" />
            </button>
          </div>

          {(!columnMapping.date || !columnMapping.amount) && (
            <p className="text-center text-xs text-amber-400">
              Devam etmek için tarih ve tutar kolonlarını eşleştirin.
            </p>
          )}
        </div>
      )}

      {/* ── Uploading ─────────────────────────────────────────────────────── */}
      {phase === "uploading" && (
        <div className="flex flex-col items-center gap-4 rounded-xl border border-border py-12">
          <RefreshCw className="h-8 w-8 animate-spin text-primary" aria-hidden="true" />
          <div className="text-center">
            <p className="font-semibold">Yükleniyor…</p>
            <p className="mt-1 text-sm text-muted-foreground">AI ajanlar hazırlanıyor</p>
          </div>
        </div>
      )}

      {/* ── Success — auto-redirects after 1.2s ──────────────────────────── */}
      {phase === "done" && jobId && (
        <div className="flex flex-col items-center gap-5 rounded-xl border border-emerald-500/30 bg-emerald-500/8 py-12">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-emerald-500/20">
            <CheckCircle2 className="h-8 w-8 text-emerald-400" aria-hidden="true" />
          </div>
          <div className="text-center">
            <p className="text-xl font-bold text-emerald-400">Yükleme Başarılı!</p>
            <p className="mt-1 text-sm text-muted-foreground">
              AI ajanlar analizi başlattı. Dashboard&apos;a yönlendiriliyorsunuz…
            </p>
          </div>
          {/* Fallback manual button in case redirect is slow */}
          <button
            onClick={goToDashboard}
            className="h-10 rounded-lg bg-primary px-8 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 press-feedback"
          >
            Hemen Git
            <ArrowRight className="ml-1.5 inline h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      )}</>)}
    </main>
  );
}
