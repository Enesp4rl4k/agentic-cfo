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
        } catch {
          return null;
        }
      },
    }),
  ],

  callbacks: {
    /**
     * Persist backend tokens + user metadata in the NextAuth JWT cookie.
     */
    async jwt({ token, user }) {
      if (user) {
        token.userId      = user.id;
        token.role        = (user as any).role;
        token.orgId       = (user as any).orgId;
        token.accessToken = (user as any).accessToken;
        token.refreshToken = (user as any).refreshToken;
      }
      return token;
    },

    /**
     * Expose needed fields to the client via useSession().
     */
    async session({ session, token }) {
      const s = session as any;
      s.user = s.user ?? {};
      s.user.id           = token.userId;
      s.user.role         = token.role;
      s.user.orgId        = token.orgId ?? null;
      s.accessToken       = token.accessToken;
      return session;
    },
  },

  secret: process.env.NEXTAUTH_SECRET,
};
