"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Search, LayoutDashboard, Upload, TrendingUp, DollarSign, Waves,
  BarChart2, MessageSquare, Brain, Zap, Users, ShieldAlert,
  FileText, Cpu, Crown, Megaphone, Layers, Shield, Settings,
  ArrowRight, Clock, Star, Hash, Sparkles, Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useCompanyContextStore } from "@/store/companyContext";
import { STORAGE_PREFIX } from "@/lib/branding";

// ── Command definitions ───────────────────────────────────────────────────────

interface Command {
  id:       string;
  label:    string;
  icon:     React.ReactNode;
  shortcut?: string;
  group:    string;
  action:   (router: ReturnType<typeof useRouter>) => void;
  keywords?: string[];
}

const COMMANDS: Command[] = [
  // Navigation
  { id: "dashboard",      label: "Dashboard",          icon: <LayoutDashboard className="h-4 w-4" />, group: "Sayfalar",   action: (r) => r.push("/"),              keywords: ["ana sayfa", "home"] },
  { id: "upload",         label: "Veri Yükle",          icon: <Upload className="h-4 w-4" />,          group: "Sayfalar",   action: (r) => r.push("/upload"),        keywords: ["upload", "dosya", "csv"] },
  { id: "chat",           label: "CFO Chat",            icon: <MessageSquare className="h-4 w-4" />,   group: "Sayfalar",   action: (r) => r.push("/chat"),          keywords: ["soru", "sorU", "ai"] },
  { id: "intelligence",   label: "Intelligence Hub",    icon: <Brain className="h-4 w-4" />,           group: "Sayfalar",   action: (r) => r.push("/intelligence"),  keywords: ["cross domain", "kernel"] },
  { id: "simulation",     label: "Simülasyon",          icon: <Zap className="h-4 w-4" />,             group: "Sayfalar",   action: (r) => r.push("/simulation"),    keywords: ["cascade", "senaryo"] },
  { id: "pnl",            label: "P&L Analizi",         icon: <DollarSign className="h-4 w-4" />,      group: "Sayfalar",   action: (r) => r.push("/pnl"),           keywords: ["gelir gider", "kar zarar"] },
  { id: "cashflow",       label: "Nakit Akışı",         icon: <Waves className="h-4 w-4" />,           group: "Sayfalar",   action: (r) => r.push("/cashflow"),      keywords: ["cash", "nakit"] },
  { id: "forecast",       label: "Tahmin",              icon: <TrendingUp className="h-4 w-4" />,      group: "Sayfalar",   action: (r) => r.push("/forecast"),      keywords: ["öngörü", "gelecek"] },
  { id: "anomalies",      label: "Anomaliler",          icon: <ShieldAlert className="h-4 w-4" />,     group: "Sayfalar",   action: (r) => r.push("/anomalies"),     keywords: ["hata", "alarm", "uyarı"] },
  { id: "trends",         label: "Trendler",            icon: <BarChart2 className="h-4 w-4" />,       group: "Sayfalar",   action: (r) => r.push("/trends"),        keywords: ["grafik", "chart"] },
  { id: "reports",        label: "Raporlar",            icon: <FileText className="h-4 w-4" />,        group: "Sayfalar",   action: (r) => r.push("/reports"),       keywords: ["pdf", "excel", "indirme"] },

  // C-Suite
  { id: "ceo",            label: "CEO Panosu",          icon: <Crown className="h-4 w-4" />,           group: "C-Suite",    action: (r) => r.push("/ceo") },
  { id: "cto",            label: "CTO Panosu",          icon: <Cpu className="h-4 w-4" />,             group: "C-Suite",    action: (r) => r.push("/cto") },
  { id: "cmo",            label: "CMO Panosu",          icon: <Megaphone className="h-4 w-4" />,       group: "C-Suite",    action: (r) => r.push("/cmo") },
  { id: "coo",            label: "COO Panosu",          icon: <Layers className="h-4 w-4" />,          group: "C-Suite",    action: (r) => r.push("/coo") },
  { id: "chro",           label: "CHRO Panosu",         icon: <Users className="h-4 w-4" />,           group: "C-Suite",    action: (r) => r.push("/chro") },
  { id: "risk",           label: "Risk Yönetimi",       icon: <Shield className="h-4 w-4" />,          group: "C-Suite",    action: (r) => r.push("/risk") },
  { id: "smmm",           label: "SMMM Portalı",        icon: <Users className="h-4 w-4" />,           group: "C-Suite",    action: (r) => r.push("/smmm"),          keywords: ["muhasebeci"] },
  { id: "smmm-onay",      label: "SMMM Onay Kuyruğu",  icon: <Hash className="h-4 w-4" />,            group: "C-Suite",    action: (r) => r.push("/smmm-onay") },

  // Settings
  { id: "integrations",   label: "Entegrasyonlar",      icon: <Settings className="h-4 w-4" />,        group: "Ayarlar",    action: (r) => r.push("/integrations"),  keywords: ["parasut", "logo", "banka"] },
  { id: "settings",       label: "Workspace Ayarları",  icon: <Settings className="h-4 w-4" />,        group: "Ayarlar",    action: (r) => r.push("/settings/workspace"), keywords: ["org", "takım"] },
];

// ── Scoring / fuzzy search ────────────────────────────────────────────────────

function score(cmd: Command, query: string): number {
  if (!query) return 0;
  const q    = query.toLowerCase();
  const text = [cmd.label, ...(cmd.keywords ?? [])].join(" ").toLowerCase();

  if (cmd.label.toLowerCase() === q)             return 100;
  if (cmd.label.toLowerCase().startsWith(q))     return 80;
  if (text.includes(q))                          return 60;

  // Partial match: count matching chars
  let i = 0, j = 0;
  while (i < q.length && j < text.length) {
    if (q[i] === text[j]) i++;
    j++;
  }
  return i === q.length ? 40 : 0;
}

// ── Recent commands (localStorage) ───────────────────────────────────────────

const RECENT_KEY = `${STORAGE_PREFIX}_recent_commands`;
const MAX_RECENT  = 5;

function getRecentIds(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]") as string[];
  } catch { return []; }
}

function addRecent(id: string) {
  const ids = [id, ...getRecentIds().filter((x) => x !== id)].slice(0, MAX_RECENT);
  localStorage.setItem(RECENT_KEY, JSON.stringify(ids));
}

// ── Main Command Palette ──────────────────────────────────────────────────────

export function CommandPalette() {
  const router         = useRouter();
  const [open,         setOpen]     = useState(false);
  const [query,        setQuery]    = useState("");
  const [activeIndex,  setActive]   = useState(0);
  const [recentIds,    setRecentIds]= useState<string[]>([]);
  const inputRef       = useRef<HTMLInputElement>(null);
  const listRef        = useRef<HTMLDivElement>(null);

  // AI Query Mode state
  const [aiMode,       setAiMode]       = useState(false);
  const [aiAnswer,     setAiAnswer]     = useState("");
  const [aiLoading,    setAiLoading]    = useState(false);
  const [followUps,    setFollowUps]    = useState<string[]>([]);
  const abortRef       = useRef<AbortController | null>(null);

  const { activeCFOJobId } = useCompanyContextStore();

  // Open with Cmd+K or Ctrl+K
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  // Load recent on open + reset AI state on close
  useEffect(() => {
    if (open) {
      setRecentIds(getRecentIds());
      setQuery("");
      setActive(0);
      setAiMode(false);
      setAiAnswer("");
      setFollowUps([]);
      setTimeout(() => inputRef.current?.focus(), 50);
    } else {
      abortRef.current?.abort();
    }
  }, [open]);

  // Stream AI answer from /query/stream
  const streamAIQuery = useCallback(async (q: string) => {
    if (!activeCFOJobId) {
      setAiAnswer("Önce bir CSV yükleyip analiz çalıştırın, ardından sorularınızı yanıtlayabilirim.");
      setAiLoading(false);
      return;
    }
    setAiLoading(true);
    setAiAnswer("");
    setFollowUps([]);
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      // POST to stream endpoint via fetch (SSE)
      const res = await fetch(`${API_URL}/api/v1/query/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q, job_id: activeCFOJobId }),
        signal: ctrl.signal,
      });

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) return;

      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6);
          if (payload === "[DONE]") { setAiLoading(false); return; }
          if (payload.startsWith("\x00FOLLOW_UPS:")) {
            try { setFollowUps(JSON.parse(payload.slice(12))); } catch {}
            continue;
          }
          setAiAnswer((prev) => prev + payload);
        }
      }
    } catch (err: any) {
      if (err.name !== "AbortError") setAiAnswer("Bir hata oluştu. Tekrar deneyin.");
    } finally {
      setAiLoading(false);
    }
  }, [activeCFOJobId]);

  // Detect AI mode: query typed but no command matches
  const filtered = query.trim()
    ? COMMANDS
        .map((cmd) => ({ cmd, s: score(cmd, query) }))
        .filter((x) => x.s > 0)
        .sort((a, b) => b.s - a.s)
        .map((x) => x.cmd)
    : [
        ...recentIds.map((id) => COMMANDS.find((c) => c.id === id)).filter(Boolean) as Command[],
        ...COMMANDS.filter((c) => !recentIds.includes(c.id)).slice(0, 8),
      ];

  const shouldAiMode = query.trim().length > 4 && filtered.length === 0;

  // Trigger AI mode
  useEffect(() => {
    if (shouldAiMode && !aiMode) {
      setAiMode(true);
      streamAIQuery(query.trim());
    } else if (!shouldAiMode && aiMode) {
      setAiMode(false);
      setAiAnswer("");
      setFollowUps([]);
      abortRef.current?.abort();
    }
  }, [shouldAiMode]);

  // Keyboard navigation
  const handleKey = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const cmd = filtered[activeIndex];
      if (cmd) runCommand(cmd);
    }
  }, [filtered, activeIndex]);

  function runCommand(cmd: Command) {
    addRecent(cmd.id);
    setOpen(false);
    cmd.action(router);
  }

  // Group the results
  const grouped: Record<string, Command[]> = {};
  filtered.forEach((cmd) => {
    const grp = query.trim() ? cmd.group : (recentIds.includes(cmd.id) ? "Son Kullanılanlar" : cmd.group);
    if (!grouped[grp]) grouped[grp] = [];
    grouped[grp].push(cmd);
  });

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh] px-4 bg-background/60 backdrop-blur-sm"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-xl border border-border bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-3 border-b border-border px-4 py-3">
          <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setActive(0); }}
            onKeyDown={handleKey}
            placeholder="Bir sayfa veya işlem arayın…"
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            aria-label="Komut ara"
          />
          <kbd className="rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground">ESC</kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-[22rem] overflow-y-auto py-2" role="listbox" aria-label="Komutlar">
          {aiMode ? (
            // ── AI Query Mode ──────────────────────────────────────────────
            <div className="px-4 py-3 space-y-3">
              <div className="flex items-center gap-2 text-xs font-semibold text-primary">
                <Sparkles className="h-3.5 w-3.5" />
                <span>CFO Yapay Zeka Yanıtı</span>
                {aiLoading && <Loader2 className="h-3 w-3 animate-spin ml-auto" />}
              </div>
              <p className="text-sm text-foreground/90 leading-relaxed whitespace-pre-wrap min-h-[2rem]">
                {aiAnswer || (aiLoading ? <span className="text-muted-foreground animate-pulse">Yanıt oluşturuluyor…</span> : null)}
              </p>
              {followUps.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Takip Soruları</p>
                  <div className="flex flex-wrap gap-2">
                    {followUps.map((fu, i) => (
                      <button
                        key={i}
                        onClick={() => { setQuery(fu); setAiMode(false); setAiAnswer(""); streamAIQuery(fu); }}
                        className="rounded-full border border-border bg-muted/50 px-3 py-1 text-xs text-muted-foreground hover:text-foreground hover:border-primary/50 hover:bg-primary/5 transition-colors"
                      >
                        {fu}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : filtered.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-muted-foreground">Sonuç bulunamadı — daha uzun bir soru yazarak CFO AI'ı sorgulayabilirsiniz</p>
          ) : (
            Object.entries(grouped).map(([group, cmds]) => (
              <div key={group}>
                <p className="px-4 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  {group}
                </p>
                {cmds.map((cmd) => {
                  const globalIdx = filtered.indexOf(cmd);
                  const isActive  = globalIdx === activeIndex;
                  return (
                    <button
                      key={cmd.id}
                      role="option"
                      aria-selected={isActive}
                      onClick={() => runCommand(cmd)}
                      onMouseEnter={() => setActive(globalIdx)}
                      className={cn(
                        "flex w-full items-center gap-3 px-4 py-2.5 text-sm transition-colors",
                        isActive ? "bg-primary/10 text-foreground" : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                      )}
                    >
                      <span className={cn("shrink-0", isActive ? "text-primary" : "")}>
                        {cmd.icon}
                      </span>
                      <span className="flex-1 text-left">{cmd.label}</span>
                      {isActive && <ArrowRight className="h-3.5 w-3.5 shrink-0 text-primary" />}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-4 border-t border-border px-4 py-2 text-[10px] text-muted-foreground">
          <span><kbd className="rounded border border-border px-1 py-0.5">↑↓</kbd> Gezin</span>
          <span><kbd className="rounded border border-border px-1 py-0.5">↵</kbd> Seç</span>
          <span><kbd className="rounded border border-border px-1 py-0.5">Ctrl K</kbd> Aç/Kapat</span>
        </div>
      </div>
    </div>
  );
}

// ── Trigger button (for top bar) ──────────────────────────────────────────────

export function CommandPaletteTrigger({ className }: { className?: string }) {
  return (
    <button
      onClick={() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }))}
      aria-label="Komut paleti aç (Ctrl+K)"
      className={cn(
        "hidden sm:flex items-center gap-2 rounded-md border border-border bg-muted/50 px-3 py-1.5",
        "text-xs text-muted-foreground hover:text-foreground hover:border-border/80 transition-colors",
        className
      )}
    >
      <Search className="h-3 w-3" />
      <span>Ara veya git…</span>
      <kbd className="ml-1 rounded border border-border px-1.5 py-0.5 text-[9px]">⌘K</kbd>
    </button>
  );
}
