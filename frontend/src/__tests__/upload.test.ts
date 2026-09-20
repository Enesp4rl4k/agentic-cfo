/**
 * Upload file validation tests.
 *
 * Tests the validation logic that governs accepted file types and size limits
 * without mounting the full upload wizard (which has many provider deps).
 */
import { describe, it, expect } from "vitest";

// ── Validation logic (extracted from upload page) ─────────────────────────────

const ACCEPTED_TYPES = new Set([
  "text/csv",
  "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/pdf",
]);

const MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024; // 50 MB

interface FileValidationResult {
  valid: boolean;
  error?: string;
}

function validateUploadFile(file: { name: string; type: string; size: number }): FileValidationResult {
  if (!ACCEPTED_TYPES.has(file.type)) {
    return { valid: false, error: `Desteklenmeyen dosya türü: ${file.type}. Sadece CSV, Excel ve PDF kabul edilir.` };
  }
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return { valid: false, error: `Dosya boyutu ${(file.size / 1024 / 1024).toFixed(1)} MB, limit 50 MB.` };
  }
  return { valid: true };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Upload file validation", () => {
  describe("accepted file types", () => {
    it("accepts CSV files", () => {
      const result = validateUploadFile({ name: "data.csv", type: "text/csv", size: 1000 });
      expect(result.valid).toBe(true);
    });

    it("accepts Excel .xlsx files", () => {
      const result = validateUploadFile({
        name: "report.xlsx",
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size: 50000,
      });
      expect(result.valid).toBe(true);
    });

    it("accepts Excel .xls files", () => {
      const result = validateUploadFile({
        name: "old-report.xls",
        type: "application/vnd.ms-excel",
        size: 30000,
      });
      expect(result.valid).toBe(true);
    });

    it("accepts PDF files", () => {
      const result = validateUploadFile({ name: "invoice.pdf", type: "application/pdf", size: 200000 });
      expect(result.valid).toBe(true);
    });
  });

  describe("rejected file types", () => {
    it("rejects image files", () => {
      const result = validateUploadFile({ name: "screenshot.png", type: "image/png", size: 500 });
      expect(result.valid).toBe(false);
      expect(result.error).toContain("Desteklenmeyen dosya türü");
    });

    it("rejects Word documents", () => {
      const result = validateUploadFile({
        name: "report.docx",
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size: 10000,
      });
      expect(result.valid).toBe(false);
    });

    it("rejects plain text files", () => {
      const result = validateUploadFile({ name: "notes.txt", type: "text/plain", size: 100 });
      expect(result.valid).toBe(false);
    });

    it("rejects JSON files", () => {
      const result = validateUploadFile({ name: "data.json", type: "application/json", size: 200 });
      expect(result.valid).toBe(false);
    });
  });

  describe("file size limits", () => {
    it("accepts files under 50 MB", () => {
      const result = validateUploadFile({
        name: "large.csv",
        type: "text/csv",
        size: 49 * 1024 * 1024,
      });
      expect(result.valid).toBe(true);
    });

    it("accepts files exactly at 50 MB", () => {
      const result = validateUploadFile({
        name: "exact.csv",
        type: "text/csv",
        size: 50 * 1024 * 1024,
      });
      expect(result.valid).toBe(true);
    });

    it("rejects files over 50 MB", () => {
      const result = validateUploadFile({
        name: "huge.csv",
        type: "text/csv",
        size: 51 * 1024 * 1024,
      });
      expect(result.valid).toBe(false);
      expect(result.error).toContain("MB");
    });
  });
});
