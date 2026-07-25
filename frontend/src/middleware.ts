/**
 * Next.js middleware — auth guard.
 *
 * Protected routes: everything under /dashboard, /upload, /pnl, etc.
 * Public routes (no auth needed):
 *   - /               (landing page)
 *   - /pricing        (pricing page)
 *   - /auth/*         (login, register)
 *   - /api/auth/*     (NextAuth endpoints)
 *   - /_next/*        (Next.js internals)
 *   - /favicon.ico
 */
export { default } from "next-auth/middleware";

export const config = {
  matcher: [
    /*
     * Protect these routes — everything under the dashboard group.
     * Public: /, /pricing, /auth/*, /api/auth/*, /_next/*, /favicon.ico
     */
    "/((?!$|pricing|auth|api/auth|_next/static|_next/image|favicon.ico).*)",
  ],
};
