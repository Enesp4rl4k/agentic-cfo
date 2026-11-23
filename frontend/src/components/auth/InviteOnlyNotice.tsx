"use client";

import Link from "next/link";
import { useI18n } from "@/hooks/useI18n";

/**
 * What the sign-up page says while registration is by invitation only (`REGISTRATION_MODE`), instead
 * of a form that could only be refused. `contact` is SUPPORT_CONTACT (an address or a URL), when set.
 */
export function InviteOnlyNotice({ contact }: { contact: string | null }) {
  const { t } = useI18n();
  const s = t.inviteOnly;
  const href = contact ? (contact.includes("@") ? `mailto:${contact}` : contact) : null;
  return (
    <div role="status" className="space-y-3 rounded-lg border border-border bg-muted/30 p-5">
      <h1 className="m-0 text-xl font-bold tracking-tight">{s.title}</h1>
      <p className="m-0 text-sm text-muted-foreground">{s.body}</p>
      <p className="m-0 text-sm">
        {href ? (
          <>
            {s.contact.split("{contact}")[0]}
            <a href={href} className="font-semibold text-primary underline-offset-4 hover:underline">
              {contact}
            </a>
          </>
        ) : (
          s.noContact
        )}
      </p>
      <Link href="/auth/login" className="text-sm font-semibold text-primary underline-offset-4 hover:underline">
        {s.signIn}
      </Link>
    </div>
  );
}
