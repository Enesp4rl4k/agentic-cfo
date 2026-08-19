"use client";

import { useRef, useEffect, useState } from "react";
import { Send, Wifi, WifiOff, Loader2, RotateCcw, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import { useWSChat } from "@/hooks/useWSChat";
import { useCompanyContextStore } from "@/store/companyContext";

// ── Typing cursor ─────────────────────────────────────────────────────────────

function TypingCursor() {
  return (
    <span className="ml-0.5 inline-block h-3.5 w-0.5 animate-pulse rounded-sm bg-current align-middle" />
  );
}

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({
  role, content, streaming,
}: { role: "user" | "assistant"; content: string; streaming?: boolean }) {
  const isUser = role === "user";
  return (
    <div className={cn("flex gap-2", isUser && "flex-row-reverse")}>
      {/* Avatar */}
      <div className={cn(
        "mt-0.5 h-6 w-6 shrink-0 rounded-full flex items-center justify-center text-[10px] font-bold",
        isUser
          ? "bg-primary/15 text-primary"
          : "bg-muted text-muted-foreground"
      )}>
        {isUser ? "S" : "AI"}
      </div>

      {/* Bubble */}
      <div className={cn(
        "max-w-[80%] rounded-lg px-3 py-2 text-sm leading-relaxed",
        isUser
          ? "bg-primary text-primary-foreground"
          : "bg-muted text-foreground"
      )}>
        {content || (streaming ? null : <span className="text-muted-foreground italic">…</span>)}
        {streaming && <TypingCursor />}
      </div>
    </div>
  );
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, { label: string; color: string; icon?: React.ReactNode }> = {
    idle:       { label: "Bağlı değil",   color: "text-muted-foreground" },
    connecting: { label: "Bağlanıyor…",   color: "text-yellow-400", icon: <Loader2 className="h-3 w-3 animate-spin" /> },
    connected:  { label: "Bağlandı",      color: "text-emerald-400", icon: <Wifi className="h-3 w-3" /> },
    streaming:  { label: "Yanıt yazıyor", color: "text-blue-400",    icon: <Zap className="h-3 w-3" /> },
    done:       { label: "Hazır",         color: "text-emerald-400", icon: <Wifi className="h-3 w-3" /> },
    error:      { label: "Hata",          color: "text-red-400",     icon: <WifiOff className="h-3 w-3" /> },
    closed:     { label: "Kapalı",        color: "text-muted-foreground", icon: <WifiOff className="h-3 w-3" /> },
  };

  const c = cfg[status] ?? cfg.idle;
  return (
    <span className={cn("flex items-center gap-1 text-[11px]", c.color)}>
      {c.icon}
      {c.label}
    </span>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface WSChatPanelProps {
  /** If provided, scope the chat to this CFO analysis job */
  jobId?: string | null;
  className?: string;
}

export function WSChatPanel({ jobId, className }: WSChatPanelProps) {
  const { orgId, activeCFOJobId } = useCompanyContextStore();
  const effectiveJobId = jobId ?? activeCFOJobId;

  const { messages, status, error, isStreaming, send, clear } = useWSChat();

  const [input, setInput]     = useState("");
  const bottomRef             = useRef<HTMLDivElement>(null);
  const inputRef              = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom on new messages/tokens
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function handleSend() {
    const q = input.trim();
    if (!q || isStreaming) return;
    send({ question: q, jobId: effectiveJobId, orgId });
    setInput("");
    inputRef.current?.focus();
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const QUICK = [
    "Nakit pisti ne kadar?",
    "En büyük gider kalemleri neler?",
    "Büyüme trendi nasıl?",
    "Kritik riskler neler?",
  ];

  return (
    <div className={cn("flex flex-col h-full min-h-[400px] max-h-[600px]", className)}>
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-3 py-2 shrink-0">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold">AI Chat</span>
          <span className="text-[10px] text-muted-foreground bg-primary/10 text-primary px-1.5 py-0.5 rounded">WS</span>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={status} />
          {messages.length > 0 && (
            <button
              onClick={clear}
              className="rounded p-1 text-muted-foreground hover:text-foreground hover:bg-muted"
              title="Sohbeti temizle"
              aria-label="Sohbeti temizle"
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full space-y-4 text-center py-8">
            <div className="rounded-full bg-muted p-3">
              <Zap className="h-6 w-6 text-muted-foreground" />
            </div>
            <div>
              <p className="text-sm font-medium">C-Suite AI Asistanı</p>
              <p className="text-xs text-muted-foreground mt-1">
                Token seviyesinde gerçek zamanlı yanıt streaming
              </p>
            </div>
            {/* Quick questions */}
            <div className="flex flex-wrap gap-2 justify-center max-w-xs">
              {QUICK.map((q) => (
                <button
                  key={q}
                  onClick={() => {
                    send({ question: q, jobId: effectiveJobId, orgId });
                  }}
                  className="rounded-full border border-border bg-muted/50 px-3 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, i) => (
            <MessageBubble
              key={i}
              role={msg.role}
              content={msg.content}
              streaming={msg.streaming}
            />
          ))
        )}

        {/* Error */}
        {error && (
          <div className="rounded border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-400">
            {error}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-border p-2 shrink-0">
        <div className="flex gap-2 items-end">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Şirket verileriniz hakkında sorun… (Enter göndermek için)"
            rows={1}
            className={cn(
              "flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm",
              "focus:outline-none focus:ring-1 focus:ring-ring",
              "min-h-[36px] max-h-[120px]"
            )}
            disabled={isStreaming}
            aria-label="Soru giriniz"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isStreaming}
            className={cn(
              "shrink-0 rounded-md p-2 transition-colors",
              "bg-primary text-primary-foreground hover:opacity-90",
              "disabled:opacity-40 disabled:cursor-not-allowed"
            )}
            aria-label="Gönder"
          >
            {isStreaming
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : <Send className="h-4 w-4" />
            }
          </button>
        </div>
        <p className="mt-1 text-[10px] text-muted-foreground px-1">
          Shift+Enter yeni satır · Enter gönder
        </p>
      </div>
    </div>
  );
}
