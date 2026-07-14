"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, DollarSign, Loader2, AlertCircle, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { apiClient } from "@/lib/api/client";

function slugify(str: string): string {
  return str
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .slice(0, 50);
}

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    org_name: "",
    org_slug: "",
    full_name: "",
    email: "",
    password: "",
  });
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (field: string) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm((prev) => {
      const next = { ...prev, [field]: e.target.value };
      // Auto-generate slug from org name
      if (field === "org_name") {
        next.org_slug = slugify(e.target.value);
      }
      return next;
    });
  };

  const passwordStrength = (() => {
    const p = form.password;
    if (!p) return null;
    if (p.length < 8) return { level: 0, label: "Too short" };
    if (p.length < 12) return { level: 1, label: "Weak" };
    const hasUpper = /[A-Z]/.test(p);
    const hasNum = /\d/.test(p);
    const hasSpecial = /[^a-zA-Z0-9]/.test(p);
    const score = (hasUpper ? 1 : 0) + (hasNum ? 1 : 0) + (hasSpecial ? 1 : 0);
    if (score >= 2) return { level: 3, label: "Strong" };
    return { level: 2, label: "Medium" };
  })();

  const strengthColors = ["bg-destructive", "bg-destructive", "bg-warning", "bg-success"];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);

    try {
      const res = await apiClient.post<{
        data: { access_token: string; user: object };
        error: null;
      }>("/auth/register", form);

      if (typeof window !== "undefined") {
        localStorage.setItem("access_token", res.data.data.access_token);
      }

      router.push("/");
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Registration failed. Please try again.";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  const isValid =
    form.org_name.length >= 2 &&
    form.org_slug.length >= 3 &&
    form.full_name.length >= 2 &&
    form.email.includes("@") &&
    form.password.length >= 8;

  return (
    <div className="flex min-h-screen bg-background">
      {/* Left panel */}
      <div className="hidden lg:flex lg:w-5/12 lg:flex-col lg:justify-between bg-card border-r border-border p-12">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary">
            <DollarSign className="h-5 w-5 text-primary-foreground" aria-hidden="true" />
          </div>
          <span className="text-lg font-semibold tracking-tight">AI CFO</span>
        </div>

        <div className="space-y-6">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">
              Everything a CFO does — automated.
            </h2>
            <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
              Upload a bank statement or CSV. Get P&L, Cash Flow, Balance Sheet,
              12-month forecast, tax analysis, and anomaly detection — in minutes.
            </p>
          </div>
          <ul className="space-y-2.5">
            {[
              "P&L Statement with EBITDA breakdown",
              "Balance Sheet & 18 financial ratios",
              "Burn rate, runway & cash conversion cycle",
              "Tax analysis (KDV, Stopaj, Kurumlar Vergisi)",
              "Anomaly & fraud detection",
              "Budget vs Actual with variance analysis",
              "12-month forecast (3 scenarios)",
              "Reports in Turkish, English, German",
            ].map((item) => (
              <li key={item} className="flex items-center gap-2.5 text-sm text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                {item}
              </li>
            ))}
          </ul>
        </div>

        <p className="text-xs text-muted-foreground">
          Free to start · No credit card required
        </p>
      </div>

      {/* Right panel */}
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-12 overflow-y-auto">
        <div className="w-full max-w-md">
          {/* Mobile logo */}
          <div className="mb-8 flex items-center gap-2 lg:hidden">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
              <DollarSign className="h-4 w-4 text-primary-foreground" aria-hidden="true" />
            </div>
            <span className="font-semibold tracking-tight">AI CFO</span>
          </div>

          <div className="mb-8">
            <h1 className="text-2xl font-bold tracking-tight">Create your account</h1>
            <p className="mt-1.5 text-sm text-muted-foreground">
              Set up your organization in 30 seconds
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            {error && (
              <div role="alert" className="flex items-start gap-2.5 rounded-lg border border-destructive/30 bg-destructive/8 px-4 py-3 text-sm text-destructive">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                {error}
              </div>
            )}

            {/* Org name + slug */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label htmlFor="org_name" className="block text-sm font-medium text-foreground">
                  Organization name
                </label>
                <input
                  id="org_name"
                  type="text"
                  required
                  value={form.org_name}
                  onChange={update("org_name")}
                  placeholder="Acme Corp"
                  className={cn(
                    "w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm",
                    "placeholder:text-muted-foreground/50",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background"
                  )}
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="org_slug" className="block text-sm font-medium text-foreground">
                  URL slug
                </label>
                <input
                  id="org_slug"
                  type="text"
                  required
                  value={form.org_slug}
                  onChange={update("org_slug")}
                  placeholder="acme-corp"
                  className={cn(
                    "w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm font-mono",
                    "placeholder:text-muted-foreground/50",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background"
                  )}
                />
                <p className="text-xs text-muted-foreground">
                  app.aicfo.com/<span className="text-foreground font-medium">{form.org_slug || "…"}</span>
                </p>
              </div>
            </div>

            {/* Full name */}
            <div className="space-y-1.5">
              <label htmlFor="full_name" className="block text-sm font-medium text-foreground">
                Your name
              </label>
              <input
                id="full_name"
                type="text"
                autoComplete="name"
                required
                value={form.full_name}
                onChange={update("full_name")}
                placeholder="Jane Smith"
                className={cn(
                  "w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm",
                  "placeholder:text-muted-foreground/50",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background"
                )}
              />
            </div>

            {/* Email */}
            <div className="space-y-1.5">
              <label htmlFor="email" className="block text-sm font-medium text-foreground">
                Work email
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={form.email}
                onChange={update("email")}
                placeholder="jane@acmecorp.com"
                className={cn(
                  "w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm",
                  "placeholder:text-muted-foreground/50",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background"
                )}
              />
            </div>

            {/* Password */}
            <div className="space-y-1.5">
              <label htmlFor="password" className="block text-sm font-medium text-foreground">
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  required
                  value={form.password}
                  onChange={update("password")}
                  placeholder="Min. 8 characters"
                  className={cn(
                    "w-full rounded-lg border border-border bg-background px-3.5 py-2.5 pr-10 text-sm",
                    "placeholder:text-muted-foreground/50",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background"
                  )}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-3 flex items-center text-muted-foreground hover:text-foreground transition-colors"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
                </button>
              </div>
              {/* Strength meter */}
              {passwordStrength && (
                <div className="space-y-1">
                  <div className="flex gap-1">
                    {[0, 1, 2].map((i) => (
                      <div
                        key={i}
                        className={cn(
                          "h-1 flex-1 rounded-full transition-colors",
                          i < passwordStrength.level
                            ? strengthColors[passwordStrength.level]
                            : "bg-muted"
                        )}
                      />
                    ))}
                  </div>
                  <p className="text-xs text-muted-foreground">{passwordStrength.label}</p>
                </div>
              )}
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={isLoading || !isValid}
              className={cn(
                "mt-2 flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground",
                "transition-opacity hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              )}
            >
              {isLoading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
              {isLoading ? "Creating account…" : "Create free account"}
            </button>

            <p className="text-center text-xs text-muted-foreground">
              By signing up, you agree to our{" "}
              <span className="underline cursor-pointer">Terms of Service</span> and{" "}
              <span className="underline cursor-pointer">Privacy Policy</span>.
            </p>
          </form>

          <p className="mt-6 text-center text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link
              href="/login"
              className="font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded"
            >
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
