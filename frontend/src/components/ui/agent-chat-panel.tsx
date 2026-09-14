"use client";
/**
 * AgentChatPanel — Universal floating chat panel.
 *
 * Connects to POST /chat/agent — uses the full CompanyContext
 * so ALL agent results (CFO, CTO, CMO, COO, CHRO, Risk) are in context.
 *
 * Usage:
 *   <AgentChatPanel agentFilter="cto" agentLabel="CTO" />
 *   <AgentChatPanel agentFilter="all" agentLabel="C-Suite AI" />
 *
 * Features:
 *   - Collapsible floating panel (bottom-right)
 *   - Suggested questions per agent
 *   - Conversation history
 *   - Follow-up suggestions
 *   - Streaming support
 */

import { useState, useRef, useEffect, useCallback, type KeyboardEvent } from "react";
import { MessageSquare, X, Send, Bot, User, ChevronDown, Sparkles, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { sendAgentChatMessage, type AgentFilter } from "@/lib/api/chat";
import { ChatEvidenceChips, type ChatEvidenceMeta } from "@/components/ui/chat-evidence-chips";

// ── Types ─────────────────────────────────────────────────────────────────────

export type { AgentFilter };

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  ts: number;
  pending?: boolean;
  error?: boolean;
  evidence?: ChatEvidenceMeta;
}

interface AgentChatPanelProps {
  /** Which agent's context to focus on. "all" = full company context. */
  agentFilter?: AgentFilter;
  /** Display label shown in the panel header */
  agentLabel?: string;
  /** Suggested starter questions */
  suggestions?: string[];
  className?: string;
}

// ── Suggested questions per agent ─────────────────────────────────────────────

const DEFAULT_SUGGESTIONS: Record<AgentFilter, string[]> = {
  all: [
    "Şirketimin en büyük riski nedir?",
    "Bu ay hangi aksiyonları öncelikli almalıyım?",
    "CFO ve CTO verileri birlikte ne söylüyor?",
  ],
  cfo: [
    "Bu ay neden zarar ettim / kâr azaldı?",
    "Nakit ne zaman biter? Önlem almalı mıyım?",
    "Hangi gider kalemini kısmalıyım?",
  ],
  cto: [
    "Teknik borcumu nasıl azaltabilirim?",
    "Bulut maliyetlerimi nasıl optimize ederim?",
    "Mühendislik verimliliğini artırmak için ne yapmalıyım?",
  ],
  cmo: [
    "En yüksek ROI'li pazarlama kanalım hangisi?",
    "CAC'imi nasıl düşürebilirim?",
    "Müşteri churn'ümü azaltmak için ne yapmalıyım?",
  ],
  coo: [
    "En büyük operasyonel darboğazım nerede?",
    "SLA ihlallerimi nasıl azaltabilirim?",
    "Süreç verimliliğimi artırmak için ne önerirsin?",
  ],
  chro: [
    "İşten ayrılma oranımı düşürmek için ne yapmalıyım?",
    "Hangi departmanda kritik yetenek riski var?",
    "Maaş politikamı gözden geçirmeli miyim?",
  ],
  risk: [
    "En kritik risklerim nelerdir?",
    "Hangi riski önce yönetmeliyim?",
    "Operasyonel risklerimi nasıl azaltırım?",
  ],
  audit: [
    "Denetim bulgularımın özeti nedir?",
    "En acil düzeltilmesi gereken kontrol eksikliği nedir?",
    "Uyumluluk durumum nasıl?",
  ],
};

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";

  return (
    <div
      className={cn(
        "flex items-start gap-2.5",
        isUser && "flex-row-reverse"
      )}
    >
      {/* Avatar */}
      <div className={cn(
        "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs",
        isUser
          ? "bg-primary/15 text-primary"
          : "bg-muted text-muted-foreground"
      )}>
        {isUser ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
      </div>

      {/* Bubble */}
      <div className={cn("max-w-[82%]", isUser && "flex flex-col items-end")}>
        <div className={cn(
          "rounded-xl px-3 py-2 text-sm leading-relaxed",
          isUser
            ? "bg-primary text-primary-foreground rounded-tr-none"
            : msg.error
            ? "bg-destructive/10 text-destructive border border-destructive/20 rounded-tl-none"
            : msg.pending
            ? "bg-muted text-muted-foreground rounded-tl-none"
            : "bg-muted text-foreground rounded-tl-none"
        )}>
          {msg.pending ? (
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-primary animate-bounce-subtle" style={{ animationDelay: "0ms" }} />
              <span className="h-1.5 w-1.5 rounded-full bg-primary animate-bounce-subtle" style={{ animationDelay: "180ms" }} />
              <span className="h-1.5 w-1.5 rounded-full bg-primary animate-bounce-subtle" style={{ animationDelay: "360ms" }} />
            </span>
          ) : (
            <span className="whitespace-pre-wrap">{msg.content}</span>
          )}
        </div>
        {!isUser && !msg.pending && msg.evidence && (
          <ChatEvidenceChips meta={msg.evidence} />
        )}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function AgentChatPanel({
  agentFilter = "all",
  agentLabel = "C-Suite AI",
  suggestions,
  className,
}: AgentChatPanelProps) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const resolvedSuggestions = suggestions ?? DEFAULT_SUGGESTIONS[agentFilter] ?? DEFAULT_SUGGESTIONS.all;
  const hasMessages = messages.length > 0;

  // Auto-scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [open]);

  const sendMessage = useCallback(async (question: string) => {
    if (!question.trim() || loading) return;

    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      content: question.trim(),
      ts: Date.now(),
    };
    const pendingMsg: ChatMessage = {
      id: `a-${Date.now()}`,
      role: "assistant",
      content: "",
      ts: Date.now(),
      pending: true,
    };

    setMessages((prev) => [...prev, userMsg, pendingMsg]);
    setInput("");
    setLoading(true);

    try {
      const { answer, evidence } = await sendAgentChatMessage(question.trim(), {
        agentFilter,
        history: [...messages, userMsg]
          .filter((m) => !m.pending && !m.error)
          .map(({ role, content }) => ({ role, content })),
      });

      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingMsg.id
            ? { ...m, content: answer, pending: false, evidence }
            : m
        )
      );
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingMsg.id
            ? {
                ...m,
                content: err instanceof Error ? err.message : "Bir hata oluştu.",
                pending: false,
                error: true,
              }
            : m
        )
      );
    } finally {
      setLoading(false);
    }
  }, [agentFilter, messages, loading]);

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  }

  const unreadCount = 0; // Could be used for notification dot

  return (
    <div className={cn("fixed bottom-5 right-5 z-50 flex flex-col items-end gap-3", className)}>
      {/* Expanded chat panel */}
      {open && (
        <div
          className={cn(
            "flex flex-col rounded-xl border border-border bg-card shadow-xl",
            "w-[360px] max-h-[560px]",
            "animate-scale-in"
          )}
          role="dialog"
          aria-label={`${agentLabel} chat paneli`}
        >
          {/* Header */}
          <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
            <div className="flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/15">
                <Sparkles className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
              </div>
              <div>
                <p className="text-sm font-semibold">{agentLabel}</p>
                <p className="text-[10px] text-muted-foreground">
                  {agentFilter === "all" ? "Tüm agent verilerine erişim var" : `${agentFilter.toUpperCase()} verilerine odaklanıyor`}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-1">
              {hasMessages && (
                <button
                  onClick={() => setMessages([])}
                  className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-state"
                  aria-label="Sohbeti sıfırla"
                  title="Sohbeti sıfırla"
                >
                  <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              )}
              <button
                onClick={() => setOpen(false)}
                className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-state"
                aria-label="Paneli kapat"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
            {!hasMessages ? (
              /* Welcome + suggestions */
              <div className="space-y-3">
                <div className="flex items-start gap-2.5">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted">
                    <Bot className="h-3.5 w-3.5 text-muted-foreground" />
                  </div>
                  <div className="rounded-xl rounded-tl-none bg-muted px-3 py-2 text-sm text-foreground">
                    Merhaba! Şirketiniz hakkında her türlü soruyu sorabilirsiniz. Tüm analiz verilerinize erişimim var.
                  </div>
                </div>

                <div>
                  <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground px-0.5">
                    Önerilen Sorular
                  </p>
                  <div className="space-y-1.5">
                    {resolvedSuggestions.map((s) => (
                      <button
                        key={s}
                        onClick={() => sendMessage(s)}
                        className={cn(
                          "w-full rounded-lg border border-border bg-card px-3 py-2 text-left text-xs text-muted-foreground",
                          "hover:border-primary/40 hover:bg-primary/5 hover:text-foreground",
                          "transition-state press-feedback"
                        )}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              messages.map((msg) => (
                <MessageBubble key={msg.id} msg={msg} />
              ))
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="border-t border-border p-3">
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Bir şey sorun… (Enter = gönder)"
                rows={1}
                disabled={loading}
                aria-label="Mesaj yaz"
                className={cn(
                  "flex-1 resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm",
                  "focus:outline-none focus:ring-1 focus:ring-ring transition-state",
                  "max-h-24 disabled:opacity-50"
                )}
                style={{ height: "auto" }}
                onInput={(e) => {
                  const el = e.target as HTMLTextAreaElement;
                  el.style.height = "auto";
                  el.style.height = Math.min(el.scrollHeight, 96) + "px";
                }}
              />
              <button
                onClick={() => sendMessage(input)}
                disabled={!input.trim() || loading}
                aria-label="Gönder"
                className={cn(
                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground",
                  "hover:opacity-90 transition-state press-feedback disabled:opacity-40"
                )}
              >
                {loading
                  ? <RefreshCw className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  : <Send className="h-3.5 w-3.5" aria-hidden="true" />
                }
              </button>
            </div>
            <p className="mt-1.5 text-[10px] text-muted-foreground/60 text-center">
              Enter → gönder · Shift+Enter → yeni satır
            </p>
          </div>
        </div>
      )}

      {/* Toggle button */}
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "Chat panelini kapat" : "Chat panelini aç"}
        aria-expanded={open}
        className={cn(
          "flex h-12 w-12 items-center justify-center rounded-full shadow-lg",
          "transition-spring press-feedback",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          open
            ? "bg-muted text-muted-foreground"
            : "bg-primary text-primary-foreground"
        )}
      >
        {open
          ? <ChevronDown className="h-5 w-5" aria-hidden="true" />
          : <MessageSquare className="h-5 w-5" aria-hidden="true" />
        }
      </button>
    </div>
  );
}
