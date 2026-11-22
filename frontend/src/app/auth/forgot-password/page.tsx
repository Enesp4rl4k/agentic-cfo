"use client";

import Link from "next/link";
import { Logo } from "@/components/ui/logo";
import { EmailRequestForm } from "@/components/auth/EmailRequestForm";
import { useI18n } from "@/hooks/useI18n";

/** Ask for a password-reset link: `POST /auth/forgot-password`; the same confirmation for every address. */
export default function ForgotPasswordPage() {
  const { t } = useI18n();
  const s = t.passwordReset.forgot;
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4 py-12">
      <div className="mb-6 flex justify-center">
        <Link href="/" className="rounded-md text-foreground"><Logo size="lg" /></Link>
      </div>
      <h1 className="mb-5 text-center text-2xl font-bold tracking-tight">{s.title}</h1>
      <EmailRequestForm endpoint="forgot-password" text={s} />
      <p className="mt-6 text-center text-sm">
        <Link href="/auth/login" className="font-semibold text-primary underline-offset-4 hover:underline">{s.back}</Link>
      </p>
    </main>
  );
}
