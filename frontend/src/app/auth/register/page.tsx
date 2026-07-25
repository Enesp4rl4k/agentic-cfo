"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import { Eye, EyeOff, Loader2, Building2 } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Step = "account" | "workspace";

export default function RegisterPage() {
  const router = useRouter();

  // Step 1: account details
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  // Step 2: workspace
  const [orgName, setOrgName] = useState("");

  const [step, setStep] = useState<Step>("account");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      // 1. Register user
      const regRes = await fetch(`${API_BASE}/api/v1/auth/register`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, full_name: fullName, role: "analyst" }),
      });
      if (!regRes.ok) {
        const data = await regRes.json();
        throw new Error(data?.detail ?? "Kayıt başarısız.");
      }

      // 2. Login to get tokens
      const loginRes = await signIn("credentials", {
        email,
        password,
        redirect: false,
      });
      if (loginRes?.error) throw new Error("Giriş başarısız.");

      // 3. Create org (need access token — use fetch directly with session)
      // Re-fetch session token via the backend login endpoint
      const tokenRes = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const tokenData = await tokenRes.json();
      const accessToken = tokenData?.data?.access_token;

      if (accessToken) {
        await fetch(`${API_BASE}/api/v1/org/create`, {
          method:  "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${accessToken}`,
          },
          body: JSON.stringify({ name: orgName }),
        });
      }

      router.push("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bir hata oluştu.");
      setStep("account");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10">
            {step === "workspace" ? (
                <Building2 className="h-6 w-6 text-primary" aria-hidden="true" />
              ) : (
                <Logo size="lg" />
              )}
            <h1 className="mt-2 text-xl font-bold tracking-tight">
              {step === "workspace" ? "Workspace Oluştur" : "Hesap Oluştur"}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
            {step === "workspace"
              ? "Ekibiniz için bir workspace adı girin"
              : "AI CFO'yu ücretsiz deneyin"}
          </p>
        </div>

        {/* Step indicator */}
        <div className="mb-6 flex items-center justify-center gap-2">
          {(["account", "workspace"] as Step[]).map((s, i) => (
            <div key={s} className="flex items-center gap-2">
              <div
                className={cn(
                  "flex h-6 w-6 items-center justify-center rounded-full text-xs font-medium",
                  s === step
                    ? "bg-primary text-primary-foreground"
                    : step === "workspace" && s === "account"
                    ? "bg-emerald-500 text-white"
                    : "bg-muted text-muted-foreground"
                )}
              >
                {step === "workspace" && s === "account" ? "✓" : i + 1}
              </div>
              {i === 0 && (
                <div className={cn("h-px w-8", step === "workspace" ? "bg-emerald-500" : "bg-muted")} />
              )}
            </div>
          ))}
        </div>

        {/* Card */}
        <div className="rounded-xl border border-border bg-card p-6 shadow-sm">
          {error && (
            <div
              role="alert"
              className="mb-4 rounded-md border border-destructive/30 bg-destructive/8 px-3 py-2.5 text-sm text-destructive"
            >
              {error}
            </div>
          )}

          {step === "account" ? (
            <form onSubmit={handleAccountStep} className="space-y-4" noValidate>
              <div className="space-y-1.5">
                <label htmlFor="fullName" className="text-xs font-medium">Ad Soyad</label>
                <input
                  id="fullName"
                  type="text"
                  autoComplete="name"
                  required
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Ahmet Yılmaz"
                  className={cn(
                    "h-9 w-full rounded-md border border-border bg-background px-3 text-sm",
                    "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  )}
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="email" className="text-xs font-medium">E-posta</label>
                <input
                  id="email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="siz@sirket.com"
                  className={cn(
                    "h-9 w-full rounded-md border border-border bg-background px-3 text-sm",
                    "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  )}
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="password" className="text-xs font-medium">Şifre</label>
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
                      "h-9 w-full rounded-md border border-border bg-background px-3 pr-9 text-sm",
                      "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    )}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    aria-label={showPassword ? "Şifreyi gizle" : "Şifreyi göster"}
                  >
                    {showPassword ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                  </button>
                </div>
              </div>

              <button
                type="submit"
                disabled={!email || !password || !fullName}
                className={cn(
                  "flex h-9 w-full items-center justify-center rounded-md bg-primary text-sm font-medium text-primary-foreground",
                  "transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                  "disabled:pointer-events-none disabled:opacity-50"
                )}
              >
                Devam Et →
              </button>
            </form>
          ) : (
            <form onSubmit={handleWorkspaceStep} className="space-y-4" noValidate>
              <div className="space-y-1.5">
                <label htmlFor="orgName" className="text-xs font-medium">
                  Workspace Adı
                </label>
                <input
                  id="orgName"
                  type="text"
                  required
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  placeholder="Acme Yazılım A.Ş."
                  className={cn(
                    "h-9 w-full rounded-md border border-border bg-background px-3 text-sm",
                    "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  )}
                />
                <p className="text-xs text-muted-foreground">
                  Ekibiniz bu workspace altında çalışacak.
                </p>
              </div>

              <button
                type="submit"
                disabled={loading || !orgName}
                className={cn(
                  "flex h-9 w-full items-center justify-center gap-2 rounded-md bg-primary text-sm font-medium text-primary-foreground",
                  "transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                  "disabled:pointer-events-none disabled:opacity-50"
                )}
              >
                {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {loading ? "Oluşturuluyor…" : "Workspace Oluştur"}
              </button>

              <button
                type="button"
                onClick={() => setStep("account")}
                className="w-full text-center text-xs text-muted-foreground transition-colors hover:text-foreground"
              >
                ← Geri
              </button>
            </form>
          )}

          <div className="mt-4 border-t border-border pt-4 text-center text-xs text-muted-foreground">
            Zaten hesabınız var mı?{" "}
            <a
              href="/auth/login"
              className="font-medium text-primary transition-opacity hover:opacity-80"
            >
              Giriş yapın
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
