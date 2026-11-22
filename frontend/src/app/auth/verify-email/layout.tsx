import type { Metadata } from "next";

/**
 * The verification link carries a one-time token. The page reads it from the URL fragment, removes it
 * from the address bar and sends it in a POST body; `no-referrer` (here and as a response header in
 * next.config.mjs) keeps the address from reaching any other site.
 */
export const metadata: Metadata = {
  referrer: "no-referrer",
  robots: { index: false, follow: false },
};

export default function VerifyEmailLayout({ children }: { children: React.ReactNode }) {
  return children;
}
