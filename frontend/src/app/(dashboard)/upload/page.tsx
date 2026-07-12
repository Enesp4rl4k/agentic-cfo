"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useDropzone } from "react-dropzone";
import { Upload, FileText, CheckCircle, AlertCircle, Loader2 } from "lucide-react";
import { useUpload, useStartAnalysis } from "@/hooks/useCFO";
import { cn } from "@/lib/utils";

type UploadState = "idle" | "uploading" | "starting" | "done" | "error";

export default function UploadPage() {
  const router = useRouter();
  const [state, setState] = useState<UploadState>("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const upload = useUpload();
  const startAnalysis = useStartAnalysis();

  const onDrop = useCallback((accepted: File[]) => {
    if (accepted[0]) setSelectedFile(accepted[0]);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "application/pdf": [".pdf"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
      "text/csv": [".csv"],
    },
    maxFiles: 1,
    maxSize: 10 * 1024 * 1024, // 10 MB
  });

  const handleSubmit = async () => {
    if (!selectedFile) return;
    setErrorMsg(null);
    try {
      setState("uploading");
      const { job_id } = await upload.mutateAsync(selectedFile);

      setState("starting");
      await startAnalysis.mutateAsync(job_id);

      setState("done");
      setTimeout(() => router.push(`/?job=${job_id}`), 1000);
    } catch (err) {
      setState("error");
      setErrorMsg(err instanceof Error ? err.message : "Upload failed.");
    }
  };

  return (
    <div className="mx-auto max-w-xl p-6">
      <h1 className="text-2xl font-bold tracking-tight">Upload Financial Document</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Supported formats: PDF, Excel (.xlsx), CSV · Max 10 MB
      </p>

      {/* Dropzone */}
      <div
        {...getRootProps()}
        className={cn(
          "mt-6 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-8 py-14 text-center transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          isDragActive
            ? "border-primary bg-primary/5"
            : selectedFile
            ? "border-green-600 bg-green-950/20"
            : "border-border hover:border-muted-foreground/50 hover:bg-muted/20"
        )}
      >
        <input {...getInputProps()} aria-label="Upload financial document" />

        {selectedFile ? (
          <>
            <FileText className="h-10 w-10 text-green-400" aria-hidden="true" />
            <p className="mt-3 font-medium text-foreground">{selectedFile.name}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {(selectedFile.size / 1024).toFixed(0)} KB · Click to replace
            </p>
          </>
        ) : (
          <>
            <Upload className="h-10 w-10 text-muted-foreground" aria-hidden="true" />
            <p className="mt-3 font-medium">
              {isDragActive ? "Drop it here" : "Drag & drop or click to browse"}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">PDF, XLSX, CSV up to 10 MB</p>
          </>
        )}
      </div>

      {/* Status message */}
      {state === "error" && errorMsg && (
        <div
          role="alert"
          className="mt-4 flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {errorMsg}
        </div>
      )}

      {state === "done" && (
        <div
          role="status"
          className="mt-4 flex items-center gap-2 rounded-lg border border-green-800/40 bg-green-950/20 px-4 py-3 text-sm text-green-400"
        >
          <CheckCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
          Analysis started — redirecting to dashboard…
        </div>
      )}

      {/* Submit button */}
      <button
        onClick={handleSubmit}
        disabled={!selectedFile || state === "uploading" || state === "starting" || state === "done"}
        className={cn(
          "mt-6 flex w-full items-center justify-center gap-2 rounded-lg px-5 py-3 text-sm font-medium transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          "bg-primary text-primary-foreground hover:bg-primary/90",
          "disabled:cursor-not-allowed disabled:opacity-50"
        )}
      >
        {(state === "uploading" || state === "starting") && (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        )}
        {state === "uploading"
          ? "Uploading…"
          : state === "starting"
          ? "Starting analysis…"
          : state === "done"
          ? "Done!"
          : "Analyze Document"}
      </button>

      <p className="mt-4 text-center text-xs text-muted-foreground">
        Your document is processed securely. The AI CFO agent will extract transactions,
        compute P&L, cash flow, and generate a 12-month forecast.
      </p>
    </div>
  );
}
