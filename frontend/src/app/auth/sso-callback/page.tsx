"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { signIn } from "next-auth/react";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * SSO Callback Page
 *
 * Called after OAuth2 redirect from backend (/auth/sso/{provider}/callback).
 * Backend appends ?access_token=...&refresh_token=...&provider=...
 *
 * This page:
 * 1. Extracts tokens from URL
 * 2. Signs in via NextAuth with the backend JWT
 * 3. Redirects to dashboard
 */
export default function SSOCallbackPage() {
  const router       = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("SSO oturumu doğrulanıyor…");

  useEffect(() => {
    async function handleCallback() {
      const accessToken  = searchParams.get("access_token");
      const refreshToken = searchParams.get("refresh_token");
      const provider     = searchParams.get("provider") ?? "sso";
      const error        = searchParams.get("error");

      if (error) {
        const reasons: Record<string, string> = {
          sso_failed:           "SSO girişi başarısız oldu.",
          state_invalid:        "Oturum süresi doldu. Lütfen tekrar deneyin.",
          provider_error:       "Sağlayıcı hatası. Lütfen tekrar deneyin.",
          provisioning_failed:  "Hesap oluşturulamadı.",
        };
        setStatus("error");
        setMessage(reasons[error] ?? "Bilinmeyen SSO hatası.");
        setTimeout(() => router.push("/auth/login?error=sso"), 3000);
        return;
      }

      if (!accessToken) {
        setStatus("error");
        setMessage("Token alınamadı. Lütfen tekrar giriş yapın.");
        setTimeout(() => router.push("/auth/login"), 3000);
        return;
      }

      try {
        // Sign in via NextAuth using the backend JWT
        const result = await signIn("credentials", {
          redirect:    false,
          access_token:  accessToken,
          refresh_token: refreshToken ?? "",
          provider,
        });

        if (result?.error) {
          throw new Error(result.error);
        }

        setStatus("success");
        setMessage(`${providerLabel(provider)} ile başarıyla giriş yapıldı`);
        setTimeout(() => router.push("/"), 1000);
      } catch (err) {
        setStatus("error");
        setMessage("Oturum oluşturulamadı. Lütfen tekrar deneyin.");
        setTimeout(() => router.push("/auth/login?error=sso_session"), 3000);
      }
    }

    handleCallback();
  }, [router, searchParams]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-6 rounded-xl border border-border bg-card p-8 text-center shadow-lg">
        {status === "loading" && (
          <Loader2 className="mx-auto h-10 w-10 animate-spin text-primary" />
        )}
        {status === "success" && (
          <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-400" />
        )}
        {status === "error" && (
          <XCircle className="mx-auto h-10 w-10 text-red-400" />
        )}

        <div className="space-y-1">
          <p className={cn(
            "font-semibold",
            status === "error" ? "text-red-400" :
            status === "success" ? "text-emerald-400" : "text-foreground"
          )}>
            {status === "loading" ? "Giriş Yapılıyor" :
             status === "success" ? "Başarılı!" : "Hata"}
          </p>
          <p className="text-sm text-muted-foreground">{message}</p>
        </div>

        {status === "error" && (
          <button
            onClick={() => router.push("/auth/login")}
            className="text-xs text-primary hover:underline"
          >
            Giriş sayfasına dön
          </button>
        )}
      </div>
    </div>
  );
}

function providerLabel(provider: string): string {
  const labels: Record<string, string> = {
    microsoft: "Microsoft",
    google:    "Google",
    github:    "GitHub",
  };
  return labels[provider] ?? provider;
}
