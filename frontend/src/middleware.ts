/**
 * Next.js middleware — authentication + role-based authorization.
 *
 * Auth guard (unauthenticated → /auth/login):
 *   Everything under /dashboard, /upload, /pnl, etc.
 *
 * Role guard (insufficient role → ACCESS_DENIED_ROUTE):
 *   Certain routes require a role class (contributor / writer / decider /
 *   billing, see @/lib/roles). Viewers cannot reach any of them; analysts only
 *   the contributor pages (upload).
 *
 * Public routes (no auth):
 *   /               (landing page)
 *   /pricing
 *   /auth/*         (login, register)
 *   /api/auth/*     (NextAuth endpoints)
 *   /_next/*
 *   /favicon.ico
 *
 * Roles are classes, not a ladder: cfo and smmm are writers, not deciders.
 */

import { withAuth, type NextRequestWithAuth } from "next-auth/middleware";
import { NextResponse } from "next/server";
import { ACCESS_DENIED_ROUTE } from "@/lib/routes";
import { ROUTE_RULES, hasRoleClass } from "@/lib/roles";

// Roles and the page → class map live in @/lib/roles, mirrored from the backend.

// ── Middleware ─────────────────────────────────────────────────────────────────

export default withAuth(
  function middleware(req: NextRequestWithAuth) {
    const { pathname } = req.nextUrl;
    const token = req.nextauth.token;
    const role  = (token?.role as string) ?? "viewer";

    // Find the first matching role rule
    const rule = ROUTE_RULES.find((r) => pathname.startsWith(r.prefix));

    if (rule && !hasRoleClass(role, rule.cls)) {
      // `(dashboard)` is a route group, not a URL segment: there is no
      // /dashboard page, so every denial used to land on Next's 404 with
      // an informative query param attached to nothing.
      const redirectUrl = req.nextUrl.clone();
      redirectUrl.pathname = ACCESS_DENIED_ROUTE;
      redirectUrl.searchParams.set("unauthorized", "1");
      redirectUrl.searchParams.set("required", rule.cls);
      return NextResponse.redirect(redirectUrl);
    }

    return NextResponse.next();
  },
  {
    // The middleware previously used next-auth's default /api/auth/signin as
    // the unauthorized target, so a bounced request made an extra hop through
    // it (which rewrote callbackUrl to an absolute URL) before reaching the
    // custom page. Pointing it at the configured pages lands directly on ours.
    pages: {
      signIn: "/auth/login",
      error: "/auth/login",
    },
    callbacks: {
      // authorized() returning false → redirects to /auth/login automatically
      authorized: ({ token }) => !!token,
    },
  }
);

export const config = {
  matcher: [
    /*
     * Protect these routes — everything under the dashboard group.
     * Public: /, /pricing, /auth/*, /api/auth/*, /api/health (the container health check, the smoke test and an
     * uptime monitor must get 200, not a redirect to the login page), /_next/*, /favicon.ico
     */
    "/((?!$|pricing|auth|api/auth|api/health$|_next/static|_next/image|favicon.ico).*)",
  ],
};
