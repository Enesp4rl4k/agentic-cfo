/**
 * Next.js middleware — authentication + role-based authorization.
 *
 * Auth guard (unauthenticated → /auth/login):
 *   Everything under /dashboard, /upload, /pnl, etc.
 *
 * Role guard (insufficient role → /dashboard):
 *   Certain routes require specific roles. Viewers and analysts
 *   cannot access write-sensitive or admin-only pages.
 *
 * Public routes (no auth):
 *   /               (landing page)
 *   /pricing
 *   /auth/*         (login, register)
 *   /api/auth/*     (NextAuth endpoints)
 *   /_next/*
 *   /favicon.ico
 *
 * Role hierarchy (least → most privileged):
 *   viewer < analyst < editor < admin < owner
 */

import { withAuth, type NextRequestWithAuth } from "next-auth/middleware";
import { NextResponse } from "next/server";

// ── Role definitions ───────────────────────────────────────────────────────────

type UserRole = "viewer" | "analyst" | "editor" | "admin" | "owner";

const ROLE_RANK: Record<UserRole, number> = {
  viewer:  0,
  analyst: 1,
  editor:  2,
  admin:   3,
  owner:   4,
};

function hasRole(userRole: string, required: UserRole): boolean {
  const rank = ROLE_RANK[userRole as UserRole] ?? -1;
  return rank >= ROLE_RANK[required];
}

// ── Route → minimum required role ─────────────────────────────────────────────

/**
 * Map of path prefixes to the minimum role required.
 * Checked in order; first match wins.
 */
const ROLE_RULES: Array<{ prefix: string; minRole: UserRole }> = [
  // Workspace settings — admin and above only
  { prefix: "/settings/workspace", minRole: "admin" },
  // Alert preferences — admin and above
  { prefix: "/settings/alerts",    minRole: "admin" },
  // Billing — owner only
  { prefix: "/settings/billing",   minRole: "owner" },
  // File upload — editor and above (viewers/analysts are read-only)
  { prefix: "/upload",             minRole: "editor" },
  // Pilot program management — admin and above
  { prefix: "/pilot",              minRole: "admin" },
];

// ── Middleware ─────────────────────────────────────────────────────────────────

export default withAuth(
  function middleware(req: NextRequestWithAuth) {
    const { pathname } = req.nextUrl;
    const token = req.nextauth.token;
    const role  = (token?.role as string) ?? "viewer";

    // Find the first matching role rule
    const rule = ROLE_RULES.find((r) => pathname.startsWith(r.prefix));

    if (rule && !hasRole(role, rule.minRole)) {
      // Redirect to dashboard with an informative query param
      const redirectUrl = req.nextUrl.clone();
      redirectUrl.pathname = "/dashboard";
      redirectUrl.searchParams.set("unauthorized", "1");
      redirectUrl.searchParams.set("required", rule.minRole);
      return NextResponse.redirect(redirectUrl);
    }

    return NextResponse.next();
  },
  {
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
     * Public: /, /pricing, /auth/*, /api/auth/*, /_next/*, /favicon.ico
     */
    "/((?!$|pricing|auth|api/auth|_next/static|_next/image|favicon.ico).*)",
  ],
};
