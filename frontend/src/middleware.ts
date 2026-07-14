import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Public paths that don't require auth
const PUBLIC_PATHS = ["/login", "/register"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow public paths
  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  // Allow API routes and static files
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname.includes(".")
  ) {
    return NextResponse.next();
  }

  // Check for access_token in Authorization header (set by frontend on navigation)
  // In SSR context we check the cookie; client navigation is handled by AuthContext
  const refreshToken = request.cookies.get("refresh_token");

  // If no refresh token at all, redirect to login
  // Note: access token is in-memory, so SSR can't check it.
  // We use a lightweight "session" cookie to indicate logged-in state.
  const sessionIndicator = request.cookies.get("_session");

  if (!sessionIndicator && !refreshToken) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match all request paths except:
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico
     */
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
