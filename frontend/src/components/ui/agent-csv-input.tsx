"use client";
/**
 * AgentCsvInput — Reusable CSV input for agent pages.
 *
 * Supports two modes:
 *   1. File dropzone  — drag & drop or click to upload a .csv / .txt file
 *   2. Text fallback  — expandable textarea for manual paste
 *
 * Usage:
 *   <AgentCsvInput
 *     label="Süreçler CSV"
 *     value={processCsv}
 *     onChange={setProcessCsv}
 *     sampleData={SAMPLE_PROCESSES_CSV}
 *     accept=".csv,.txt"
 *   />
 */

import { useCallback, useState, useRef } from "react";
import { FileText, Upload, X, ChevronDown, ChevronUp, Copy, Check } from "lucide-react";
import { cn } from "@/lib/utils";

interface AgentCsvInputProps {
  /** Field label shown above the dropzone */
  label: string;
  /** Controlled value — raw CSV string */
  value: string;
  /** Called when value changes (file drop or paste) */
  onChange: (value: string) => void;
  /** Placeholder shown in the textarea fallback */
  placeholder?: string;
  /** Sample data string — shown via "Örnek Veri" button */
  sampleData?: string;
  /** Accepted file extensions, e.g. ".csv,.txt" (default: ".csv") */
  accept?: string;
  /** Textarea rows when expanded (default: 6) */
  rows?: number;
  /** Whether the input is disabled */
  disabled?: boolean;
  /** Optional description shown below the label */
  description?: string;
}

export function AgentCsvInput({
  label,
  value,
  onChange,
  placeholder = "CSV verisi yapıştırın veya dosya yükleyin…",
  sampleData,
  accept = ".csv,.txt",
  rows = 6,
  disabled = false,
  description,
}: AgentCsvInputProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [showTextarea, setShowTextarea] = useState(false);
  const [copied, setCopied] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const hasValue = value.trim().length > 0;

  // ── File reading ────────────────────────────────────────────────────────────

  const readFile = useCallback(
    (file: File) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        const text = (e.target?.result as string) ?? "";
        onChange(text);
        setFileName(file.name);
        setShowTextarea(false);
      };
      reader.readAsText(file, "utf-8");
    },
    [onChange]
  );

  // ── Drag & drop handlers ────────────────────────────────────────────────────

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) readFile(file);
    },
    [readFile]
  );

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) readFile(file);
    },
    [readFile]
  );

  // ── Copy sample data ────────────────────────────────────────────────────────

  const handleLoadSample = useCallback(() => {
    if (!sampleData) return;
    onChange(sampleData);
    setFileName("örnek-veri.csv");
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [sampleData, onChange]);

  // ── Clear ────────────────────────────────────────────────────────────────────

  const handleClear = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onChange("");
      setFileName(null);
      setShowTextarea(false);
      if (inputRef.current) inputRef.current.value = "";
    },
    [onChange]
  );

  // ── Dropzone click ──────────────────────────────────────────────────────────

  const handleDropzoneClick = useCallback(() => {
    if (disabled) return;
    inputRef.current?.click();
  }, [disabled]);

  return (
    <div className="space-y-1.5">
      {/* Label row */}
      <div className="flex items-center justify-between">
        <label className="block text-xs font-medium text-foreground">
          {label}
        </label>
        <div className="flex items-center gap-2">
          {sampleData && (
            <button
              type="button"
              onClick={handleLoadSample}
              disabled={disabled}
              className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-primary transition-colors disabled:opacity-40"
            >
              {copied ? (
                <Check className="h-3 w-3 text-emerald-400" aria-hidden="true" />
              ) : (
                <Copy className="h-3 w-3" aria-hidden="true" />
              )}
              Örnek veri
            </button>
          )}
          {hasValue && (
            <button
              type="button"
              onClick={() => setShowTextarea((v) => !v)}
              className="flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
            >
              {showTextarea ? (
                <><ChevronUp className="h-3 w-3" aria-hidden="true" />Gizle</>
              ) : (
                <><ChevronDown className="h-3 w-3" aria-hidden="true" />Düzenle</>
              )}
            </button>
          )}
        </div>
      </div>

      {description && (
        <p className="text-[10px] text-muted-foreground">{description}</p>
      )}

      {/* Hidden file input */}
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="sr-only"
        aria-label={`${label} dosyası seç`}
        onChange={handleFileChange}
        disabled={disabled}
      />

      {/* Dropzone */}
      {!showTextarea && (
        <div
          role="button"
          tabIndex={disabled ? -1 : 0}
          aria-label={`${label} — dosya yükle veya sürükle bırak`}
          onClick={handleDropzoneClick}
          onKeyDown={(e) => e.key === "Enter" && handleDropzoneClick()}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={cn(
            "relative flex min-h-[72px] cursor-pointer items-center gap-3 rounded-lg border-2 border-dashed px-4 py-3 transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            disabled && "cursor-default opacity-50",
            isDragOver
              ? "border-primary bg-primary/5"
              : hasValue
              ? "border-emerald-600/40 bg-emerald-950/10"
              : "border-border hover:border-muted-foreground/50 hover:bg-muted/10"
          )}
        >
          {hasValue ? (
            <>
              <FileText className="h-5 w-5 shrink-0 text-emerald-400" aria-hidden="true" />
              <div className="flex-1 min-w-0">
                <p className="truncate text-sm font-medium text-foreground">
                  {fileName ?? "Veri yüklendi"}
                </p>
                <p className="text-[10px] text-muted-foreground">
                  {value.split("\n").length} satır
                  {" · "}Değiştirmek için tıkla veya
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setShowTextarea(true); }}
                    className="ml-1 underline hover:text-foreground"
                  >
                    düzenle
                  </button>
                </p>
              </div>
              <button
                type="button"
                aria-label="Veriyi temizle"
                onClick={handleClear}
                className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </>
          ) : (
            <>
              <Upload className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden="true" />
              <div>
                <p className="text-sm text-muted-foreground">
                  {isDragOver ? "Bırakın!" : "CSV dosyası sürükle & bırak veya tıkla"}
                </p>
                <p className="text-[10px] text-muted-foreground/60">
                  {accept.replace(/\./g, "").toUpperCase()} · Maks 5 MB
                </p>
              </div>
            </>
          )}
        </div>
      )}

      {/* Textarea fallback (expanded when showTextarea = true) */}
      {showTextarea && (
        <div className="relative">
          <textarea
            value={value}
            onChange={(e) => { onChange(e.target.value); setFileName(null); }}
            placeholder={placeholder}
            rows={rows}
            disabled={disabled}
            aria-label={label}
            className={cn(
              "w-full rounded-lg border border-input bg-background px-3 py-2 font-mono text-xs",
              "focus:outline-none focus:ring-1 focus:ring-ring",
              "resize-y placeholder:text-muted-foreground/50 disabled:opacity-50"
            )}
          />
          <button
            type="button"
            aria-label="Düzenlemeyi kapat"
            onClick={() => setShowTextarea(false)}
            className="absolute right-2 top-2 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  );
}
