"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import {
  Eye, EyeOff, Loader2, ArrowRight, Building2,
  CheckCircle2, Users, TrendingUp,
} from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { AuthBrandPanel } from "@/components/auth/AuthBrandPanel";
import { Logo } from "@/components/ui/logo";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Step = "account" | "workspace";

const BRAND_FEATURES = [
  { icon: TrendingUp, text: "12 AI ajan paralel çalışır"  },
  { icon: Users,      text: "Tüm C-Suite kararlarını destekler" },
  { icon: CheckCircle2, text: "14 gün ücretsiz, kredi kartı yok" },
];

export default function RegisterPage() {
  const router = useRouter();

  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [orgName, setOrgName]   = useState("");
  const [step, setStep]         = useState<Step>("account");
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);

  async function handleAccountStep(e: FormEvent) {
    e.preventDefault();
    if (!email || !password || !fullName) return;
    if (password.length < 8) {
      setError("Şifre en az 8 karakter olmalıdır.");
      return;
    }
    setError(null);
    setStep("workspace");
  }

  async function handleWorkspaceStep(e: FormEvent) {
    e.preventDefault();
    if (!orgName) return;

    setLoading(true);
    setError(null);

    try {
      const regRes = await fetch(`${API_BASE}/api/v1/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // The API assigns the initial analyst role server-side; clients must
        // not submit privilege fields during public registration.
        body: JSON.stringify({ email, password, full_name: fullName }),
      });
      if (!regRes.ok) {
        const data = await regRes.json();
        throw new Error(data?.detail ?? "Kayıt başarısız.");
      }

      const loginRes = await signIn("credentials", { email, password, redirect: false });
      if (loginRes?.error) throw new Error("Giriş başarısız.");

      const tokenRes = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const tokenData = await tokenRes.json();
      const accessToken = tokenData?.data?.access_token;

      if (accessToken) {
        await fetch(`${API_BASE}/api/v1/org/create`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
          body: JSON.stringify({ name: orgName }),
        });
        // The session was signed in before the workspace existed, as an
        // analyst with no organisation. Sign in again so its role and
        // organisation are the owner's.
        await signIn("credentials", { email, password, redirect: false });
      }

      // "/" is the marketing landing page (see lib/routes.ts). Someone who has
      // just signed up goes to the setup steps instead.
      router.push("/baslangic");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bir hata oluştu.");
      setStep("account");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen">

      {/* ── Left: brand panel ──────────────────────────────────────────────── */}
      <AuthBrandPanel items={BRAND_FEATURES} />

      {/* ── Right: register form ────────────────────────────────────────────── */}
      <div className="flex flex-1 flex-col items-center justify-center px-4 py-12 sm:px-8">
        <div className="w-full max-w-sm">

          {/* Mobile logo */}
          <div className="mb-6 flex justify-center lg:hidden">
            <Link href="/" className="rounded-md text-foreground"><Logo size="lg" /></Link>
          </div>

          {/* Header */}
          <div className="mb-6">
            <h1 className="text-2xl font-bold tracking-tight">
              {step === "workspace" ? "Workspace Oluştur" : "Ücretsiz Başla"}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {step === "workspace"
                ? "Ekibiniz için bir isim girin"
                : "Kayıt ol, 14 gün ücretsiz dene"}
            </p>
          </div>

          {/* Step indicator */}
          <div className="mb-6 flex items-center gap-2">
            {(["account", "workspace"] as Step[]).map((s, i) => (
              <div key={s} className="flex items-center gap-2">
                <div
                  className={cn(
                    "flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold transition-colors",
                    s === step
                      ? "bg-primary text-primary-foreground"
                      : step === "workspace" && s === "account"
                      ? "bg-emerald-500 text-white"
                      : "bg-muted text-muted-foreground"
                  )}
                  aria-label={`Adım ${i + 1}`}
                >
                  {step === "workspace" && s === "account" ? "✓" : i + 1}
                </div>
                <span className="text-xs text-muted-foreground">
                  {s === "account" ? "Hesap" : "Workspace"}
                </span>
                {i === 0 && (
                  <div className={cn("h-px w-6", step === "workspace" ? "bg-emerald-500" : "bg-border")} />
                )}
              </div>
            ))}
          </div>

          {/* Error */}
          {error && (
            <div
              role="alert"
              className="mb-4 rounded-lg border border-destructive/20 bg-destructive/8 px-3.5 py-2.5 text-sm text-destructive"
            >
              {error}
            </div>
          )}

          {/* Step 1: account */}
          {step === "account" && (
            <form onSubmit={handleAccountStep} className="space-y-4" noValidate>
              <div className="space-y-1.5">
                <label htmlFor="fullName" className="text-xs font-medium text-foreground/80">
                  Ad Soyad
                </label>
                <input
                  id="fullName"
                  type="text"
                  autoComplete="name"
                  required
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Ahmet Yılmaz"
                  className={cn(
                    "h-10 w-full rounded-lg border border-border bg-muted/30 px-3.5 text-sm",
                    "placeholder:text-muted-foreground",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-transparent",
                    "transition-colors"
                  )}
                />
              </div>

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
                    "placeholder:text-muted-foreground",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-transparent",
                    "transition-colors"
                  )}
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="password" className="text-xs font-medium text-foreground/80">
                  Şifre
                </label>
                <div className="relative">
                  <input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="new-password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="En az 8 karakter"
                    className={cn(
                      "h-10 w-full rounded-lg border border-border bg-muted/30 px-3.5 pr-10 text-sm",
                      "placeholder:text-muted-foreground",
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
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                {password.length > 0 && password.length < 8 && (
                  <p className="text-xs text-destructive">En az 8 karakter gerekli</p>
                )}
              </div>

              <button
                type="submit"
                disabled={!email || !password || !fullName || password.length < 8}
                className={cn(
                  "flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-primary text-sm font-semibold text-primary-foreground",
                  "transition-opacity hover:opacity-90",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                  "disabled:pointer-events-none disabled:opacity-50",
                  "press-feedback"
                )}
              >
                Devam Et
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </button>
            </form>
          )}

          {/* Step 2: workspace */}
          {step === "workspace" && (
            <form onSubmit={handleWorkspaceStep} className="space-y-4" noValidate>
              <div className="space-y-1.5">
                <label htmlFor="orgName" className="text-xs font-medium text-foreground/80">
                  Workspace Adı
                </label>
                <div className="relative">
                  <Building2 className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                  <input
                    id="orgName"
                    type="text"
                    required
                    autoFocus
                    value={orgName}
                    onChange={(e) => setOrgName(e.target.value)}
                    placeholder="Acme Yazılım A.Ş."
                    className={cn(
                      "h-10 w-full rounded-lg border border-border bg-muted/30 pl-10 pr-3.5 text-sm",
                      "placeholder:text-muted-foreground",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-transparent",
                      "transition-colors"
                    )}
                  />
                </div>
                <p className="text-xs text-muted-foreground">
                  Ekibiniz bu workspace altında çalışacak.
                </p>
              </div>

              <button
                type="submit"
                disabled={loading || !orgName}
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
                {loading ? "Oluşturuluyor…" : "Workspace Oluştur"}
              </button>

              <button
                type="button"
                onClick={() => setStep("account")}
                className="w-full text-center text-xs text-muted-foreground transition-colors hover:text-foreground"
              >
                ← Geri dön
              </button>
            </form>
          )}

          {/* Footer */}
          <p className="mt-6 text-center text-sm text-muted-foreground">
            Zaten hesabınız var mı?{" "}
            <Link
              href="/auth/login"
              className="font-semibold text-primary transition-opacity hover:opacity-80"
            >
              Giriş yapın
            </Link>
          </p>

          <p className="mt-3 text-center text-xs text-muted-foreground">
            Kayıt olarak{" "}
            <a href="#" className="underline underline-offset-2 hover:text-foreground">
              Kullanım Şartları
            </a>{" "}
            ve{" "}
            <a href="#" className="underline underline-offset-2 hover:text-foreground">
              Gizlilik Politikası
            </a>
            &apos;nı kabul etmiş olursunuz.
          </p>
        </div>
      </div>
    </div>
  );
}
