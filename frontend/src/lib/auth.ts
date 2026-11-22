/**
 * NextAuth configuration — credentials provider that authenticates
 * against the FastAPI backend JWT endpoint.
 *
 * Session strategy: JWT (stateless, stored in HttpOnly cookie).
 * The backend access_token is stored in the NextAuth JWT and forwarded
 * to API calls via the Authorization header.
 */
import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import { freshToken } from "@/lib/authRefresh";
import { syncIdentity } from "@/lib/sessionIdentity";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const authOptions: NextAuthOptions = {
  // Use JWT strategy — no DB adapter needed on the frontend
  session: { strategy: "jwt", maxAge: 7 * 24 * 60 * 60 },

  pages: {
    signIn:  "/auth/login",
    signOut: "/auth/login",
    error:   "/auth/login",
  },

  providers: [
    CredentialsProvider({
      id:   "credentials",
      name: "Email & Password",
      credentials: {
        email:    { label: "Email",    type: "email" },
        password: { label: "Password", type: "password" },
        access_token:  { label: "SSO access token", type: "text" },
        refresh_token: { label: "SSO refresh token", type: "text" },
        provider:      { label: "SSO provider", type: "text" },
      },

      async authorize(credentials) {
        if (credentials?.access_token) {
          try {
            const res = await fetch(`${API_BASE}/api/v1/auth/me`, {
              headers: { Authorization: `Bearer ${credentials.access_token}` },
            });
            if (!res.ok) return null;

            const json = await res.json();
            const user = json?.data;
            if (!user?.user_id || !user?.email) return null;

            return {
              id: user.user_id,
              email: user.email,
              name: user.full_name ?? user.email,
              role: user.role,
              orgId: user.org_id ?? null,
              accessToken: credentials.access_token,
              refreshToken: credentials.refresh_token ?? "",
            };
          } catch {
            return null;
          }
        }

        if (!credentials?.email || !credentials?.password) return null;

        try {
          const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              email:    credentials.email,
              password: credentials.password,
            }),
          });

          if (res.status === 403) {
            const refused = await res.json().catch(() => null);
            // The address is not verified yet: the login page says so and offers the link again.
            if (refused?.data?.state === "email_unverified") throw new Error("email_unverified");
          }
          if (!res.ok) return null;

          const json = await res.json();
          const data = json?.data;
          if (!data?.access_token) return null;

          return {
            id:            data.user.user_id,
            email:         data.user.email,
            name:          data.user.full_name ?? data.user.email,
            role:          data.user.role,
            orgId:         data.user.org_id ?? null,
            accessToken:   data.access_token,
            refreshToken:  data.refresh_token,
          };
        } catch (err) {
          if (err instanceof Error && err.message === "email_unverified") throw err;
          return null;
        }
      },
    }),
  ],

  callbacks: {
    /**
     * Persist backend tokens + user metadata in the NextAuth JWT cookie.
     */
    async jwt({ token, user, trigger }) {
      if (user) {
        token.userId       = user.id;
        token.role         = user.role;
        token.orgId        = user.orgId;
        token.accessToken  = user.accessToken;
        token.refreshToken = user.refreshToken;
        return token;
      }
      // Every getSession() passes here: trade the refresh token for a new
      // access token shortly before the 30-minute one expires.
      const fresh = await freshToken(token, { apiBase: API_BASE });
      // `useSession().update()` after creating or switching organisation: the
      // role and organisation in the cookie are the ones from sign-in.
      return trigger === "update" ? syncIdentity(fresh, { apiBase: API_BASE }) : fresh;
    },

    /**
     * Expose needed fields to the client via useSession().
     */
    async session({ session, token }) {
      session.user = {
        ...session.user,
        id:    token.userId,
        role:  token.role,
        orgId: token.orgId ?? null,
      };
      session.accessToken = token.accessToken;
      session.error       = token.error;
      return session;
    },
  },

  secret: process.env.NEXTAUTH_SECRET,
};
