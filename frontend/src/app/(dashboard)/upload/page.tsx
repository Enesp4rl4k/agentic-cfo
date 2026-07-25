"use client";

import { useState, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useDropzone } from "react-dropzone";
import {
  Upload,
  FileText,
  CheckCircle,
  AlertCircle,
  Loader2,
  Activity,
  Clock,
  ChevronRight,
  ChevronLeft,
  X,
  Plus,
  Building2,
  Users,
  Megaphone,
  Settings,
  Cpu,
} from "lucide-react";
import { useUpload, useStartAnalysis, useJobStatus } from "@/hooks/useCFO";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { AgentProgressPanel } from "@/components/ui/agent-progress";
import { FeedbackWidget } from "@/components/ui/feedback-widget";

// ── Types ─────────────────────────────────────────────────────────────────────

type WizardStep = "cfo" | "domains" | "review" | "running";
type UploadPhase = "idle" | "uploading" | "starting" | "polling" | "done" | "error";

interface DomainFile {
  domain: string;
  source_type: string;
  file: File;
  label: string;
}

// ── Step labels (Türkçe) ──────────────────────────────────────────────────────

const STEP_LABELS: Record<string, string> = {
  data_ingestion: "İşlemler çıkarılıyor",
  pnl:            "Gelir tablosu hesaplanıyor",
  cashflow:       "Nakit akışı analiz ediliyor",
  forecast:       "Tahmin oluşturuluyor",
  anomaly:        "Anomaliler taranıyor",
  tax:            "Vergi takvimi hazırlanıyor",
  budget:         "Bütçe karşılaştırması yapılıyor",
  alert:          "Uyarılar değerlendiriliyor",
  report:         "Rapor oluşturuluyor",
  review_gate:    "İnceleme noktası",
};

const PIPELINE_STEPS = [
  "data_ingestion", "pnl", "cashflow", "forecast", "report",
];

// ── Domain config ─────────────────────────────────────────────────────────────

const DOMAIN_CONFIG = [
  {
    domain: "cto",
    label: "Teknoloji (CTO)",
    icon: Cpu,
    description: "Bulut maliyetleri, teknik borç, olaylar ve sprint verisini analiz eder",
    color: "text-blue-400",
    bg: "bg-blue-950/20 border-blue-800/40",
    sources: [
      { source_type: "cloud_billing", label: "Bulut Faturası (AWS/GCP/Azure CSV)", accept: ".csv" },
      { source_type: "git_log",       label: "Git Log (git log --oneline çıktısı)", accept: ".txt,.csv" },
      { source_type: "incident_log",  label: "Olay Kayıtları (CSV)", accept: ".csv" },
      { source_type: "sprint_data",   label: "Sprint Verisi (CSV)", accept: ".csv" },
    ],
  },
  {
    domain: "chro",
    label: "İnsan Kaynakları (CHRO)",
    icon: Users,
    description: "Çalışan sayısı, işten ayrılma ve ücret verilerini analiz eder",
    color: "text-purple-400",
    bg: "bg-purple-950/20 border-purple-800/40",
    sources: [
      { source_type: "headcount",    label: "Çalışan Listesi (CSV)", accept: ".csv,.xlsx" },
      { source_type: "attrition",    label: "İşten Ayrılma Verisi (CSV)", accept: ".csv" },
      { source_type: "compensation", label: "Ücret Tablosu (CSV)", accept: ".csv,.xlsx" },
    ],
  },
  {
    domain: "cmo",
    label: "Pazarlama (CMO)",
    icon: Megaphone,
    description: "Kampanya performansı, dönüşüm hunisi ve kohort analizlerini yapar",
    color: "text-emerald-400",
    bg: "bg-emerald-950/20 border-emerald-800/40",
    sources: [
      { source_type: "campaign", label: "Kampanya Metrikleri (CSV)", accept: ".csv" },
      { source_type: "funnel",   label: "Dönüşüm Hunisi (CSV)", accept: ".csv" },
      { source_type: "cohort",   label: "Kohort Analizi (CSV)", accept: ".csv" },
    ],
  },
  {
    domain: "coo",
    label: "Operasyon (COO)",
    icon: Settings,
    description: "SLA uyumu, süreç verimliliği ve kaynak kullanımını ölçer",
    color: "text-amber-400",
    bg: "bg-amber-950/20 border-amber-800/40",
    sources: [
      { source_type: "sla",      label: "SLA Verileri (CSV)", accept: ".csv" },
      { source_type: "process",  label: "Süreç Metrikleri (CSV)", accept: ".csv" },
      { source_type: "resource", label: "Kaynak Kullanımı (CSV)", accept: ".csv" },
    ],
  },
];

// ── Pipeline progress bileşeni ────────────────────────────────────────────────

function StepIcon({ ok, inProgress }: { ok?: boolean; inProgress?: boolean }) {
  if (inProgress) return <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" aria-hidden="true" />;
  if (ok === true)  return <CheckCircle className="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />;
  if (ok === false) return <AlertCircle className="h-3.5 w-3.5 text-destructive" aria-hidden="true" />;
  return <div className="h-3.5 w-3.5 rounded-full border border-border" aria-hidden="true" />;
}

// ── Adım 1: Banka ekstresi dropzone ──────────────────────────────────────────

function CFODropzone({
  file,
  onFile,
  disabled,
}: {
  file: File | null;
  onFile: (f: File) => void;
  disabled: boolean;
}) {
  const onDrop = useCallback((accepted: File[]) => {
    if (accepted[0]) onFile(accepted[0]);
  }, [onFile]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "application/pdf": [".pdf"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
      "text/csv": [".csv"],
    },
    maxFiles: 1,
    maxSize: 10 * 1024 * 1024,
    disabled,
  });

  return (
    <div
      {...getRootProps()}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-8 py-12 text-center transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        disabled
          ? "cursor-default opacity-60"
          : isDragActive
          ? "border-primary bg-primary/5"
          : file
          ? "border-emerald-600 bg-emerald-950/20"
          : "border-border hover:border-muted-foreground/50 hover:bg-muted/20"
      )}
    >
      <input {...getInputProps()} aria-label="Banka ekstresi yükle" />
      {file ? (
        <>
          <FileText className="h-10 w-10 text-emerald-400" aria-hidden="true" />
          <p className="mt-3 font-medium text-foreground">{file.name}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {(file.size / 1024).toFixed(0)} KB · Değiştirmek için tıkla
          </p>
        </>
      ) : (
        <>
          <Upload className="h-10 w-10 text-muted-foreground" aria-hidden="true" />
          <p className="mt-3 font-medium">
            {isDragActive ? "Bırakın!" : "Sürükle & bırak veya tıkla"}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">PDF, XLSX, CSV · Maks 10 MB</p>
        </>
      )}
    </div>
  );
}

// ── Adım 2: Domain dosyaları ──────────────────────────────────────────────────

function DomainFileRow({
  source,
  domainColor,
  file,
  onFile,
  onRemove,
}: {
  source: { source_type: string; label: string; accept: string };
  domainColor: string;
  file?: File;
  onFile: (f: File) => void;
  onRemove: () => void;
}) {
  const onDrop = useCallback((accepted: File[]) => {
    if (accepted[0]) onFile(accepted[0]);
  }, [onFile]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: source.accept.split(",").reduce((acc, ext) => {
      const mimeMap: Record<string, string> = {
        ".csv": "text/csv",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".txt": "text/plain",
        ".xls": "application/vnd.ms-excel",
      };
      const mime = mimeMap[ext.trim()];
      if (mime) acc[mime] = [ext.trim()];
      return acc;
    }, {} as Record<string, string[]>),
    maxFiles: 1,
    maxSize: 10 * 1024 * 1024,
  });

  return (
    <div className="flex items-center gap-3">
      <div
        {...getRootProps()}
        className={cn(
          "flex flex-1 cursor-pointer items-center gap-2.5 rounded-lg border px-3 py-2.5 text-sm transition-colors",
          isDragActive
            ? "border-primary bg-primary/5"
            : file
            ? "border-emerald-600/40 bg-emerald-950/10"
            : "border-border hover:border-muted-foreground/40 hover:bg-muted/10"
        )}
      >
        <input {...getInputProps()} />
        {file ? (
          <>
            <FileText className="h-4 w-4 shrink-0 text-emerald-400" aria-hidden="true" />
            <span className="flex-1 truncate text-sm">{file.name}</span>
            <span className="text-xs text-muted-foreground">
              {(file.size / 1024).toFixed(0)} KB
            </span>
          </>
        ) : (
          <>
            <Plus className={cn("h-4 w-4 shrink-0", domainColor)} aria-hidden="true" />
            <span className="text-muted-foreground">{source.label}</span>
          </>
        )}
      </div>
      {file && (
        <button
          onClick={onRemove}
          className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          aria-label="Dosyayı kaldır"
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      )}
    </div>
  );
}

// ── Özet kartı (Adım 3) ───────────────────────────────────────────────────────

function ReviewSummary({
  cfoFile,
  domainFiles,
}: {
  cfoFile: File;
  domainFiles: DomainFile[];
}) {
  const byDomain = DOMAIN_CONFIG.map((d) => ({
    ...d,
    files: domainFiles.filter((f) => f.domain === d.domain),
  }));

  return (
    <div className="space-y-3">
      {/* CFO */}
      <div className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3">
        <Building2 className="h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-muted-foreground">Finansal Veri (CFO)</p>
          <p className="truncate text-sm font-medium">{cfoFile.name}</p>
        </div>
        <CheckCircle className="h-4 w-4 shrink-0 text-emerald-400" aria-hidden="true" />
      </div>

      {/* Domain dosyaları */}
      {byDomain.map((d) =>
        d.files.length > 0 ? (
          <div key={d.domain} className={cn("rounded-lg border px-4 py-3", d.bg)}>
            <div className="mb-2 flex items-center gap-2">
              <d.icon className={cn("h-4 w-4", d.color)} aria-hidden="true" />
              <p className="text-xs font-medium text-muted-foreground">{d.label}</p>
              <span className="ml-auto text-xs text-muted-foreground">{d.files.length} dosya</span>
            </div>
            {d.files.map((f, i) => (
              <p key={i} className="truncate text-sm text-muted-foreground">
                • {f.file.name}
              </p>
            ))}
          </div>
        ) : null
      )}

      {domainFiles.length === 0 && (
        <p className="text-xs text-muted-foreground">
          Domain dosyası eklenmedi — yalnızca CFO analizi çalışacak.
        </p>
      )}
    </div>
  );
}

// ── Pipeline progress bileşeni ────────────────────────────────────────────────

function PipelineProgress({
  status,
  logs,
}: {
  status: string;
  logs: { step: string; ok: boolean; detail: string | null; confidence: number | null }[];
}) {
  const completedSteps = new Set(logs.map((l) => l.step));
  const runningIndex = PIPELINE_STEPS.findIndex((s) => !completedSteps.has(s));

  return (
    <div className="mt-4 w-full space-y-1.5">
      <p className="mb-2 flex items-center gap-1.5 text-xs text-muted-foreground">
        <Activity className="h-3 w-3 animate-pulse text-primary" aria-hidden="true" />
        Agent çalışıyor: <span className="font-medium text-foreground">{status}</span>
      </p>
      {PIPELINE_STEPS.map((step, i) => {
        const log = logs.find((l) => l.step === step);
        const isRunning = i === runningIndex && status !== "completed" && status !== "failed";
        return (
          <div
            key={step}
            className={cn(
              "flex items-center gap-2.5 rounded-md border px-3 py-2 text-xs transition-colors",
              log
                ? log.ok
                  ? "border-emerald-500/20 bg-emerald-950/20 text-emerald-400"
                  : "border-destructive/30 bg-destructive/8 text-destructive"
                : isRunning
                ? "border-primary/30 bg-primary/5 text-primary"
                : "border-border bg-card text-muted-foreground"
            )}
          >
            <StepIcon ok={log?.ok} inProgress={isRunning} />
            <span className="flex-1 font-medium">{STEP_LABELS[step] ?? step}</span>
            {log?.confidence != null && (
              <span className="tabular-nums opacity-60">
                %{(log.confidence * 100).toFixed(0)}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Ana sayfa ─────────────────────────────────────────────────────────────────

export default function UploadPage() {
  const router = useRouter();
  const { success, error: toastError } = useToast();

  // Wizard state
  const [wizardStep, setWizardStep] = useState<WizardStep>("cfo");
  const [phase, setPhase] = useState<UploadPhase>("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  // File state
  const [cfoFile, setCfoFile] = useState<File | null>(null);
  const [domainFiles, setDomainFiles] = useState<DomainFile[]>([]);

  const upload = useUpload();
  const startAnalysis = useStartAnalysis();

  const { data: job } = useJobStatus(activeJobId, phase === "polling");

  // Job status watcher
  useEffect(() => {
    if (!job) return;
    if (job.status === "completed") {
      setPhase("done");
      success("Analiz tamamlandı", "Dashboard'a yönlendiriliyor…");
      setTimeout(() => router.push(`/?job=${activeJobId}`), 1500);
    } else if (job.status === "failed") {
      setPhase("error");
      const msg = job.error ?? "Analiz başarısız.";
      setErrorMsg(msg);
      toastError("Analiz başarısız", msg);
    } else if (job.status === "awaiting_review") {
      setPhase("done");
      success("İnceleme gerekli", "Agent güven skoru düşük — lütfen onaylayın.");
      setTimeout(() => router.push(`/?job=${activeJobId}`), 1000);
    }
  }, [job?.status, activeJobId, router, success, toastError]);

  // Domain file helpers
  const addDomainFile = (domain: string, source_type: string, label: string, file: File) => {
    setDomainFiles((prev) => {
      const filtered = prev.filter(
        (f) => !(f.domain === domain && f.source_type === source_type)
      );
      return [...filtered, { domain, source_type, label, file }];
    });
  };

  const removeDomainFile = (domain: string, source_type: string) => {
    setDomainFiles((prev) =>
      prev.filter((f) => !(f.domain === domain && f.source_type === source_type))
    );
  };

  // Submit — upload CFO file, upload domain files, start analysis
  const handleSubmit = async () => {
    if (!cfoFile) return;
    setErrorMsg(null);

    try {
      // 1. Upload banka ekstresi
      setPhase("uploading");
      setWizardStep("running");
      const { job_id } = await upload.mutateAsync(cfoFile);
      setActiveJobId(job_id);

      // 2. Domain dosyalarını yükle (paralel)
      if (domainFiles.length > 0) {
        const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
        await Promise.allSettled(
          domainFiles.map(async (df) => {
            const form = new FormData();
            form.append("file", df.file);
            await fetch(
              `${apiBase}/api/v1/datasource/${job_id}/${df.domain}/${df.source_type}`,
              { method: "POST", body: form }
            );
          })
        );
      }

      // 3. Analizi başlat
      setPhase("starting");
      await startAnalysis.mutateAsync(job_id);
      setPhase("polling");
    } catch (err) {
      setPhase("error");
      setErrorMsg(err instanceof Error ? err.message : "Yükleme başarısız.");
    }
  };

  const isRunning = phase === "uploading" || phase === "starting" || phase === "polling";
  const wizardSteps: WizardStep[] = ["cfo", "domains", "review"];
  const stepIndex = wizardSteps.indexOf(wizardStep as WizardStep);

  // ── Running view ──────────────────────────────────────────────────────────

  if (wizardStep === "running") {
    return (
      <div className="mx-auto max-w-xl p-6">
        <h1 className="text-xl font-bold tracking-tight">Analiz çalışıyor</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          AI CFO agent'ı verilerinizi işliyor…
        </p>

        {(phase === "uploading" || phase === "starting") && (
          <div className="mt-6 flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />
            {phase === "uploading" ? "Dosya yükleniyor…" : "Analiz başlatılıyor…"}
          </div>
        )}

        {(phase === "polling" || phase === "starting") && activeJobId && (
          <AgentProgressPanel
            jobId={activeJobId}
            className="mt-6"
            onComplete={(status) => {
              if (status === "completed") {
                setPhase("done");
                success("Analiz tamamlandı", "Dashboard'a yönlendiriliyor…");
                setTimeout(() => router.push(`/?job=${activeJobId}`), 1500);
              } else if (status === "awaiting_review") {
                setPhase("done");
              } else if (status === "failed" || status === "error") {
                setPhase("error");
                setErrorMsg("Pipeline başarısız oldu. Tekrar deneyin.");
              }
            }}
          />
        )}

        {phase === "done" && job?.status === "completed" && (
          <>
            <div
              role="status"
              className="mt-6 flex items-center gap-2 rounded-lg border border-emerald-800/40 bg-emerald-950/20 px-4 py-3 text-sm text-emerald-400"
            >
              <CheckCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
              Analiz tamamlandı — dashboard'a yönlendiriliyor…
            </div>
            <div className="mt-4">
              <FeedbackWidget jobId={activeJobId ?? undefined} pageContext="upload_complete" />
            </div>
          </>
        )}

        {phase === "done" && job?.status === "awaiting_review" && (
          <div
            role="status"
            className="mt-6 flex items-center gap-2 rounded-lg border border-yellow-700/40 bg-yellow-950/20 px-4 py-3 text-sm text-yellow-400"
          >
            <Clock className="h-4 w-4 shrink-0" aria-hidden="true" />
            İnceleme gerekli — yönlendiriliyor…
          </div>
        )}

        {phase === "error" && errorMsg && (
          <div
            role="alert"
            className="mt-6 space-y-3"
          >
            <div className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              {errorMsg}
            </div>
            <button
              onClick={() => { setPhase("idle"); setErrorMsg(null); setActiveJobId(null); setWizardStep("cfo"); }}
              className="w-full rounded-lg border border-border px-5 py-2.5 text-sm text-muted-foreground hover:bg-muted transition-colors"
            >
              Baştan başla
            </button>
          </div>
        )}
      </div>
    );
  }

  // ── Wizard view ───────────────────────────────────────────────────────────

  return (
    <div className="mx-auto max-w-xl p-6">
      {/* Breadcrumb */}
      <div className="mb-6 flex items-center gap-1.5 text-xs text-muted-foreground">
        {["Finansal Veri", "Ek Veriler", "Özet & Başlat"].map((label, i) => (
          <span key={i} className="flex items-center gap-1.5">
            {i > 0 && <ChevronRight className="h-3 w-3" aria-hidden="true" />}
            <span className={cn(
              "font-medium",
              i === stepIndex ? "text-foreground" : ""
            )}>
              {label}
            </span>
          </span>
        ))}
      </div>

      {/* ── Adım 1: Banka ekstresi ── */}
      {wizardStep === "cfo" && (
        <>
          <h1 className="text-xl font-bold tracking-tight">Finansal belge yükle</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Banka ekstrenizi, Excel aktarımınızı veya CSV dosyanızı yükleyin.
            Akbank, Garanti, İş Bankası ve Ziraat formatları otomatik tanınır.
          </p>

          <CFODropzone
            file={cfoFile}
            onFile={setCfoFile}
            disabled={false}
          />

          <div className="mt-2 rounded-lg border border-border bg-muted/30 px-3 py-2.5">
            <p className="text-xs text-muted-foreground">
              <span className="font-medium text-foreground">Desteklenen formatlar:</span>{" "}
              PDF banka ekstresi, Excel (.xlsx), CSV · Maks 10 MB ·
              Verileriniz güvenli şekilde işlenir.
            </p>
          </div>

          <button
            onClick={() => setWizardStep("domains")}
            disabled={!cfoFile}
            className={cn(
              "mt-6 flex w-full items-center justify-center gap-2 rounded-lg px-5 py-3 text-sm font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              "bg-primary text-primary-foreground hover:bg-primary/90",
              "disabled:cursor-not-allowed disabled:opacity-50"
            )}
          >
            Devam et
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </button>
        </>
      )}

      {/* ── Adım 2: Domain dosyaları ── */}
      {wizardStep === "domains" && (
        <>
          <h1 className="text-xl font-bold tracking-tight">Ek veriler (isteğe bağlı)</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Bu verilerle AI daha derin bir analiz yapabilir. İstediğinizi atlayabilirsiniz.
          </p>

          <div className="mt-5 space-y-4">
            {DOMAIN_CONFIG.map((d) => (
              <details key={d.domain} className={cn("rounded-lg border", d.bg)}>
                <summary className="flex cursor-pointer list-none items-center gap-2.5 px-4 py-3 text-sm font-medium">
                  <d.icon className={cn("h-4 w-4 shrink-0", d.color)} aria-hidden="true" />
                  <span className="flex-1">{d.label}</span>
                  {domainFiles.filter((f) => f.domain === d.domain).length > 0 && (
                    <span className="rounded-full bg-emerald-800/30 px-1.5 py-0.5 text-xs text-emerald-400">
                      {domainFiles.filter((f) => f.domain === d.domain).length} dosya
                    </span>
                  )}
                  <ChevronRight className="h-3.5 w-3.5 text-muted-foreground transition-transform [[open]_&]:rotate-90" aria-hidden="true" />
                </summary>
                <div className="space-y-2 border-t border-border/50 px-4 py-3">
                  <p className="mb-2 text-xs text-muted-foreground">{d.description}</p>
                  {d.sources.map((src) => {
                    const existing = domainFiles.find(
                      (f) => f.domain === d.domain && f.source_type === src.source_type
                    );
                    return (
                      <DomainFileRow
                        key={src.source_type}
                        source={src}
                        domainColor={d.color}
                        file={existing?.file}
                        onFile={(f) => addDomainFile(d.domain, src.source_type, src.label, f)}
                        onRemove={() => removeDomainFile(d.domain, src.source_type)}
                      />
                    );
                  })}
                </div>
              </details>
            ))}
          </div>

          <div className="mt-6 flex gap-3">
            <button
              onClick={() => setWizardStep("cfo")}
              className="flex items-center gap-1.5 rounded-lg border border-border px-4 py-2.5 text-sm text-muted-foreground hover:bg-muted transition-colors"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              Geri
            </button>
            <button
              onClick={() => setWizardStep("review")}
              className={cn(
                "flex flex-1 items-center justify-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium transition-colors",
                "bg-primary text-primary-foreground hover:bg-primary/90"
              )}
            >
              {domainFiles.length > 0 ? "Özete geç" : "Atla, devam et"}
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </>
      )}

      {/* ── Adım 3: Özet ve başlat ── */}
      {wizardStep === "review" && cfoFile && (
        <>
          <h1 className="text-xl font-bold tracking-tight">Analizi başlat</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Yüklenen dosyaları kontrol edin ve analizi başlatın.
          </p>

          <div className="mt-5">
            <ReviewSummary cfoFile={cfoFile} domainFiles={domainFiles} />
          </div>

          <div className="mt-6 flex gap-3">
            <button
              onClick={() => setWizardStep("domains")}
              className="flex items-center gap-1.5 rounded-lg border border-border px-4 py-2.5 text-sm text-muted-foreground hover:bg-muted transition-colors"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              Geri
            </button>
            <button
              onClick={handleSubmit}
              disabled={isRunning}
              className={cn(
                "flex flex-1 items-center justify-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium transition-colors",
                "bg-primary text-primary-foreground hover:bg-primary/90",
                "disabled:cursor-not-allowed disabled:opacity-50"
              )}
            >
              {isRunning && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
              {isRunning ? "Başlatılıyor…" : "Analizi Başlat"}
            </button>
          </div>

          <p className="mt-4 text-center text-xs text-muted-foreground">
            AI CFO agent'ı işlemleri çıkaracak, gelir tablosu + nakit akışı hesaplayacak
            ve 12 aylık tahmin üretecek.
          </p>
        </>
      )}
    </div>
  );
}
