"use client";

import { useState, useRef, useEffect, useCallback, FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import {
  Send, Bot, User, Upload, RotateCcw, Copy, Check,
  ChevronRight, Sparkles, TrendingUp, AlertTriangle, DollarSign,
} from "lucide-react";
import { sendChatMessage } from "@/lib/api/cfo";
import type { ChatMessage } from "@/lib/api/cfo";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

type Message = ChatMessage & {
  id: string;
  pending?: boolean;
  error?: boolean;
  ts: number;
};

// ── Suggestion groups ─────────────────────────────────────────────────────────

const SUGGESTION_GROUPS = [
  {
    label: "Finansal Durum",
    icon: DollarSign,
    color: "text-emerald-400",
    questions: [
      "En büyük 3 gider kalemim neler?",
      "Bu ayın brüt ve net marjı nedir?",
      "EBITDA durumum nasıl?",
    ],
  },
  {
    label: "Nakit & Tahmin",
    icon: TrendingUp,
    color: "text-blue-400",
    questions: [
      "Önümüzdeki 3 ayda nakit pozisyonum ne olur?",
      "Nakit pisti ne kadar?",
      "Baz senaryoda 12 aylık net nakit nedir?",
    ],
  },
  {
    label: "Risk & Uyarılar",
    icon: AlertTriangle,
    color: "text-amber-400",
    questions: [
      "Kritik anomaliler neler?",
      "Hangi kategoride bütçemi aştım?",
      "Vergi yükümlülüklerim nelerdir?",
    ],
  },
];

// Follow-up suggestions shown after assistant response
const FOLLOWUP_CHIPS = [
  "Bunu detaylandırır mısın?",
  "Nasıl iyileştirilebilir?",
  "Sektör ortalamasıyla kıyasla",
  "Aksiyonları listele",
];

// ── Markdown-lite renderer ────────────────────────────────────────────────────

function renderMarkdown(text: string): React.ReactNode[] {
  const lines = text.split("\n");
  const nodes: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Bold amounts: ₺123.456 or **text**
    const renderInline = (s: string) => {
      const parts = s.split(/(\*\*[^*]+\*\*|₺[\d.,]+|%[\d.,]+)/g);
      return parts.map((p, pi) => {
        if (p.startsWith("**") && p.endsWith("**")) {
          return <strong key={pi} className="font-semibold text-foreground">{p.slice(2, -2)}</strong>;
        }
        if (p.startsWith("₺") || p.startsWith("%")) {
          return <span key={pi} className="font-semibold text-primary tabular-nums">{p}</span>;
        }
        return p;
      });
    };

    // Heading
    if (line.startsWith("### ")) {
      nodes.push(<h3 key={i} className="mt-3 mb-1 text-sm font-semibold text-foreground">{line.slice(4)}</h3>);
    } else if (line.startsWith("## ")) {
      nodes.push(<h2 key={i} className="mt-3 mb-1 text-sm font-bold text-foreground">{line.slice(3)}</h2>);
    }
    // Bullet list item
    else if (line.startsWith("- ") || line.startsWith("• ")) {
      nodes.push(
        <div key={i} className="flex gap-2 text-sm leading-relaxed">
          <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary/60" aria-hidden="true" />
          <span>{renderInline(line.slice(2))}</span>
        </div>
      );
    }
    // Numbered list
    else if (/^\d+\.\s/.test(line)) {
      const num = line.match(/^(\d+)\./)?.[1];
      nodes.push(
        <div key={i} className="flex gap-2 text-sm leading-relaxed">
          <span className="shrink-0 text-xs font-semibold tabular-nums text-primary/70 min-w-[1.2rem]">{num}.</span>
          <span>{renderInline(line.replace(/^\d+\.\s/, ""))}</span>
        </div>
      );
    }
    // Horizontal rule
    else if (line === "---" || line === "***") {
      nodes.push(<hr key={i} className="my-2 border-border/50" />);
    }
    // Empty line
    else if (line.trim() === "") {
      nodes.push(<div key={i} className="h-1.5" />);
    }
    // Normal paragraph
    else {
      nodes.push(
        <p key={i} className="text-sm leading-relaxed">
          {renderInline(line)}
        </p>
      );
    }
    i++;
  }
  return nodes;
}

// ── Typing indicator ──────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1 px-1 py-0.5" aria-label="AI is thinking">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40"
          style={{
            animation: `bounce 1.2s ease-in-out ${i * 0.2}s infinite`,
          }}
        />
      ))}
      <style>{`
        @keyframes bounce {
          0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
          30% { transform: translateY(-4px); opacity: 1; }
        }
      `}</style>
    </div>
  );
}

// ── Copy button ───────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard not available
    }
  };

  return (
    <button
      onClick={handleCopy}
      className={cn(
        "rounded p-1 opacity-0 transition-all group-hover:opacity-100",
        "text-muted-foreground hover:text-foreground",
        "focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      )}
      aria-label="Copy message"
    >
      {copied
        ? <Check className="h-3 w-3 text-emerald-400" aria-hidden="true" />
        : <Copy className="h-3 w-3" aria-hidden="true" />
      }
    </button>
  );
}

// ── Timestamp ─────────────────────────────────────────────────────────────────

function Timestamp({ ts }: { ts: number }) {
  return (
    <time
      dateTime={new Date(ts).toISOString()}
      className="text-[10px] text-muted-foreground/50 tabular-nums"
    >
      {new Date(ts).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}
    </time>
  );
}

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({
  message,
  showFollowups,
  onFollowup,
}: {
  message: Message;
  showFollowups?: boolean;
  onFollowup?: (q: string) => void;
}) {
  const isUser = message.role === "user";

  return (
    <div className={cn("group flex gap-2.5", isUser ? "flex-row-reverse" : "flex-row")}>
      {/* Avatar */}
      <div
        className={cn(
          "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
          isUser ? "bg-primary/20" : "bg-muted"
        )}
        aria-hidden="true"
      >
        {isUser
          ? <User className="h-3.5 w-3.5 text-primary" />
          : <Bot className="h-3.5 w-3.5 text-muted-foreground" />
        }
      </div>

      {/* Content column */}
      <div className={cn("flex max-w-[78%] flex-col gap-1", isUser ? "items-end" : "items-start")}>
        {/* Bubble */}
        <div
          className={cn(
            "rounded-2xl px-4 py-3",
            isUser
              ? "rounded-tr-sm bg-primary text-primary-foreground"
              : message.error
              ? "rounded-tl-sm border border-destructive/30 bg-destructive/8 text-destructive"
              : "rounded-tl-sm border border-border bg-card text-foreground"
          )}
        >
          {message.pending ? (
            <TypingIndicator />
          ) : isUser ? (
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="space-y-0.5">
              {renderMarkdown(message.content)}
            </div>
          )}
        </div>

        {/* Footer: timestamp + copy */}
        {!message.pending && (
          <div className={cn("flex items-center gap-1.5", isUser ? "flex-row-reverse" : "flex-row")}>
            <Timestamp ts={message.ts} />
            {!isUser && <CopyButton text={message.content} />}
          </div>
        )}

        {/* Follow-up chips — shown after last assistant message */}
        {showFollowups && !message.pending && !isUser && onFollowup && (
          <div className="mt-1 flex flex-wrap gap-1.5">
            {FOLLOWUP_CHIPS.map((chip) => (
              <button
                key={chip}
                onClick={() => onFollowup(chip)}
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-1 text-[11px]",
                  "text-muted-foreground bg-card",
                  "hover:border-primary/50 hover:text-foreground transition-colors",
                  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                )}
              >
                <ChevronRight className="h-2.5 w-2.5" aria-hidden="true" />
                {chip}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Empty / welcome state ─────────────────────────────────────────────────────

function WelcomeState({ onSend }: { onSend: (q: string) => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-6 px-4 py-8">
      <div className="text-center">
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
          <Sparkles className="h-6 w-6 text-primary" aria-hidden="true" />
        </div>
        <h2 className="text-base font-semibold">CFO Asistanı</h2>
        <p className="mt-1.5 max-w-xs text-sm text-muted-foreground leading-relaxed">
          Finansal verileriniz hakkında Türkçe soru sorun. Gerçek veri üzerinden analiz yapar.
        </p>
      </div>

      <div className="w-full max-w-lg space-y-3">
        {SUGGESTION_GROUPS.map((group) => {
          const Icon = group.icon;
          return (
            <div key={group.label}>
              <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                <Icon className={cn("h-3 w-3", group.color)} aria-hidden="true" />
                {group.label}
              </div>
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-3">
                {group.questions.map((q) => (
                  <button
                    key={q}
                    onClick={() => onSend(q)}
                    className={cn(
                      "rounded-lg border border-border bg-card px-3 py-2 text-left text-xs text-muted-foreground",
                      "transition-colors hover:border-primary/40 hover:bg-primary/5 hover:text-foreground",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    )}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── No job state ──────────────────────────────────────────────────────────────

function NoJobState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center px-6">
      <div className="mb-4 rounded-full bg-muted p-4">
        <Upload className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold">Önce analiz başlatın</h2>
      <p className="mt-1.5 max-w-xs text-sm text-muted-foreground leading-relaxed">
        Finansal belge yükleyin, analiz tamamlandıktan sonra CFO asistanını kullanabilirsiniz.
      </p>
      <a
        href="/upload"
        className={cn(
          "mt-5 inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground",
          "transition-opacity hover:opacity-90",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        )}
      >
        Belge Yükle
        <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
      </a>
    </div>
  );
}

// ── Auto-resize textarea ──────────────────────────────────────────────────────

function useAutoResize(value: string) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
  }, [value]);
  return ref;
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useAutoResize(input);

  // Auto-scroll on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const send = useCallback(async (question: string) => {
    if (!question.trim() || !jobId || loading) return;

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: question.trim(),
      ts: Date.now(),
    };
    const pendingMsg: Message = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: "",
      pending: true,
      ts: Date.now(),
    };

    setMessages((prev) => [...prev, userMsg, pendingMsg]);
    setInput("");
    setLoading(true);

    try {
      const history: ChatMessage[] = messages.map(({ role, content }) => ({ role, content }));
      const answer = await sendChatMessage(jobId, question.trim(), history);

      setMessages((prev) => [
        ...prev.slice(0, -1),
        { id: pendingMsg.id, role: "assistant", content: answer, ts: Date.now() },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev.slice(0, -1),
        {
          id: pendingMsg.id,
          role: "assistant",
          content: `Bir hata oluştu: ${err instanceof Error ? err.message : "Bilinmeyen hata"}`,
          error: true,
          ts: Date.now(),
        },
      ]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }, [jobId, loading, messages]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    send(input);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  };

  if (!jobId) return <NoJobState />;

  const lastAssistantIdx = messages.map((m, i) => ({ m, i }))
    .filter(({ m }) => m.role === "assistant" && !m.pending)
    .pop()?.i ?? -1;

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border bg-card/50 px-5 py-3 backdrop-blur">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10">
            <Bot className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
          </div>
          <div>
            <p className="text-sm font-semibold leading-none">CFO Asistanı</p>
            <p className="mt-0.5 text-[10px] text-muted-foreground">
              {loading ? "Yanıt üretiliyor…" : "Hazır"}
            </p>
          </div>
        </div>
        {messages.length > 0 && (
          <button
            onClick={() => setMessages([])}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground",
              "hover:bg-muted hover:text-foreground transition-colors",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            )}
            aria-label="Konuşmayı temizle"
          >
            <RotateCcw className="h-3 w-3" aria-hidden="true" />
            Temizle
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-5 space-y-5 sm:px-6">
        {messages.length === 0
          ? <WelcomeState onSend={send} />
          : messages.map((msg, i) => (
              <MessageBubble
                key={msg.id}
                message={msg}
                showFollowups={i === lastAssistantIdx}
                onFollowup={send}
              />
            ))
        }
        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-border bg-background/95 px-4 py-3 backdrop-blur sm:px-6">
        <form onSubmit={handleSubmit}>
          <div className={cn(
            "flex items-end gap-2 rounded-xl border border-border bg-card px-3 py-2",
            "focus-within:border-primary/50 focus-within:ring-1 focus-within:ring-primary/20 transition-all"
          )}>
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Finansal verileriniz hakkında soru sorun…"
              rows={1}
              disabled={loading}
              className={cn(
                "flex-1 resize-none bg-transparent py-0.5 text-sm leading-relaxed",
                "placeholder:text-muted-foreground/60",
                "focus-visible:outline-none",
                "disabled:cursor-not-allowed disabled:opacity-50",
              )}
              style={{ minHeight: "24px" }}
              aria-label="Chat mesajı"
            />
            <button
              type="submit"
              disabled={!input.trim() || loading}
              className={cn(
                "mb-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
                "bg-primary text-primary-foreground",
                "transition-all hover:opacity-90 disabled:opacity-30",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              )}
              aria-label="Gönder"
            >
              <Send className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
          <p className="mt-1.5 text-center text-[10px] text-muted-foreground/50">
            Enter ile gönder · Shift+Enter ile yeni satır · AI yanıtları muhasebeciye danışılarak doğrulanmalıdır.
          </p>
        </form>
      </div>
    </div>
  );
}
