"use client";

import { useState, FormEvent } from "react";
import { signIn } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { APP_HOME } from "@/lib/routes";
import { Eye, EyeOff, Loader2, ArrowRight, Shield, Zap, BarChart3 } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { brand } from "@/lib/branding";

// ── Brand panel feature list ──────────────────────────────────────────────────
const FEATURES = [
  { icon: Zap,       text: "5 dakikada ilk CFO analiziniz" },
  { icon: BarChart3, text: "12 AI ajan — CFO, CEO, CTO ve daha fazlası" },
  { icon: Shield,    text: "KVKK & SOC2 uyumlu, SSL şifreli" },
];

// ── SSO providers ─────────────────────────────────────────────────────────────
const SSO_PROVIDERS = [
  {
    id: "microsoft",
    label: "Microsoft ile devam et",
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
        <rect x="0" y="0" width="8.5" height="8.5" fill="#F25022" />
        <rect x="9.5" y="0" width="8.5" height="8.5" fill="#7FBA00" />
        <rect x="0" y="9.5" width="8.5" height="8.5" fill="#00A4EF" />
        <rect x="9.5" y="9.5" width="8.5" height="8.5" fill="#FFB900" />
      </svg>
    ),
  },
  {
    id: "google",
    label: "Google ile devam et",
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
        <path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" />
        <path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z" />
        <path fill="#FBBC05" d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" />
        <path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" />
      </svg>
    ),
  },
];

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // Defaulting to "/" sent people who signed in straight to the marketing
  // page — the same trap as the post-upload redirect.
  const callbackUrl = searchParams.get("callbackUrl") ?? APP_HOME;

  const [email, setEmail]           = useState("");
  const [password, setPassword]     = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!email || !password) return;

    setLoading(true);
    setError(null);

    try {
      const result = await signIn("credentials", {
        email,
        password,
        redirect: false,
      });

      if (result?.error) {
        setError("E-posta veya şifre hatalı. Lütfen tekrar deneyin.");
      } else {
        router.push(callbackUrl);
        router.refresh();
      }
    } catch {
      setError("Giriş yapılırken bir hata oluştu.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen">

      {/* ── Left: brand panel ──────────────────────────────────────────────── */}
      <div
        className="relative hidden w-[42%] flex-col justify-between overflow-hidden p-10 lg:flex"
        style={{
          background:
            "linear-gradient(145deg, oklch(0.13 0.035 262) 0%, oklch(0.10 0.028 255) 100%)",
        }}
      >
        {/* Glow */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(ellipse 80% 60% at 30% 20%, oklch(0.62 0.26 262 / 0.15) 0%, transparent 70%)",
          }}
        />

        {/* Logo */}
        <div className="relative z-10">
          <Link href="/" className="inline-flex items-center gap-2 text-sm font-bold text-foreground">
            <span
              className="flex h-8 w-8 items-center justify-center rounded-lg text-sm font-black text-white"
              style={{ background: "linear-gradient(135deg, oklch(0.62 0.26 262), oklch(0.55 0.22 220))" }}
              aria-hidden="true"
            >
              C
            </span>
            <span>{brand.name}</span>
          </Link>
        </div>

        {/* Center copy */}
        <div className="relative z-10 space-y-6">
          <div>
            <h2 className="text-2xl font-bold leading-tight text-foreground">
              Tüm C-Suite kararları,
              <br />
              <span
                style={{
                  background: "linear-gradient(135deg, oklch(0.75 0.22 262), oklch(0.65 0.20 220))",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  backgroundClip: "text",
                }}
              >
                yapay zeka ile
              </span>
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Muhasebe verinizi yükleyin, 5 dakikada kurumsal içgörüler alın.
            </p>
          </div>

          <ul className="space-y-3">
            {FEATURES.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/15">
                  <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
                </div>
                <span className="text-sm text-foreground/80">{text}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Bottom trust */}
        <div className="relative z-10 flex flex-wrap gap-2">
          {["KVKK", "SOC2", "SSL", "GDPR"].map((badge) => (
            <span
              key={badge}
              className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/50"
            >
              {badge}
            </span>
          ))}
        </div>
      </div>

      {/* ── Right: login form ───────────────────────────────────────────────── */}
      <div className="flex flex-1 flex-col items-center justify-center px-4 py-12 sm:px-8">
        <div className="w-full max-w-sm">

          {/* Header */}
          <div className="mb-8 text-center lg:text-left">
            {/* Mobile logo */}
            <div className="mb-6 flex justify-center lg:hidden">
              <Link href="/">
                <span
                  className="flex h-10 w-10 items-center justify-center rounded-xl text-lg font-black text-white"
                  style={{ background: "linear-gradient(135deg, oklch(0.62 0.26 262), oklch(0.55 0.22 220))" }}
                  aria-hidden="true"
                >
                  C
                </span>
              </Link>
            </div>
            <h1 className="text-2xl font-bold tracking-tight">Tekrar Hoş Geldiniz</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Hesabınıza giriş yapın
            </p>
          </div>

          {/* SSO buttons */}
          <div className="mb-5 space-y-2">
            {SSO_PROVIDERS.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => signIn(p.id)}
                className="flex h-10 w-full items-center justify-center gap-3 rounded-lg border border-border bg-card text-sm font-medium transition-colors hover:bg-muted press-feedback focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {p.icon}
                {p.label}
              </button>
            ))}
          </div>

          {/* Divider */}
          <div className="relative mb-5">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-border" />
            </div>
            <div className="relative flex justify-center">
              <span className="bg-background px-3 text-xs text-muted-foreground">
                veya e-posta ile
              </span>
            </div>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            {error && (
              <div
                role="alert"
                className="rounded-lg border border-destructive/20 bg-destructive/8 px-3.5 py-2.5 text-sm text-destructive"
              >
                {error}
              </div>
            )}

            {/* Email */}
            <div className="space-y-1.5">
              <label htmlFor="email" className="text-xs font-medium text-foreground/80">
                E-posta
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="siz@sirket.com"
                className={cn(
                  "h-10 w-full rounded-lg border border-border bg-muted/30 px-3.5 text-sm",
                  "placeholder:text-muted-foreground/60",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-transparent",
                  "transition-colors"
                )}
              />
            </div>

            {/* Password */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label htmlFor="password" className="text-xs font-medium text-foreground/80">
                  Şifre
                </label>
                <a
                  href="/auth/forgot-password"
                  className="text-xs text-muted-foreground transition-colors hover:text-primary"
                >
                  Şifremi unuttum
                </a>
              </div>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className={cn(
                    "h-10 w-full rounded-lg border border-border bg-muted/30 px-3.5 pr-10 text-sm",
                    "placeholder:text-muted-foreground/60",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-transparent",
                    "transition-colors"
                  )}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none"
                  aria-label={showPassword ? "Şifreyi gizle" : "Şifreyi göster"}
                >
                  {showPassword
                    ? <EyeOff className="h-4 w-4" />
                    : <Eye className="h-4 w-4" />
                  }
                </button>
              </div>
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={loading || !email || !password}
              className={cn(
                "flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-primary text-sm font-semibold text-primary-foreground",
                "transition-opacity hover:opacity-90",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                "disabled:pointer-events-none disabled:opacity-50",
                "press-feedback"
              )}
            >
              {loading
                ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                : <ArrowRight className="h-4 w-4" aria-hidden="true" />
              }
              {loading ? "Giriş yapılıyor…" : "Giriş Yap"}
            </button>
          </form>

          {/* Footer */}
          <p className="mt-6 text-center text-sm text-muted-foreground">
            Hesabınız yok mu?{" "}
            <Link
              href="/auth/register"
              className="font-semibold text-primary transition-opacity hover:opacity-80"
            >
              Ücretsiz kayıt olun
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
