/**
 * Augment NextAuth types to include our custom fields
 * (role, orgId, accessToken).
 */
import "next-auth";
import "next-auth/jwt";

declare module "next-auth" {
  interface Session {
    accessToken: string;
    user: {
      id:     string;
      email:  string;
      name?:  string | null;
      image?: string | null;
      role:   string;
      orgId:  string | null;
    };
  }

  interface User {
    id:           string;
    email:        string;
    name?:        string | null;
    role:         string;
    orgId:        string | null;
    accessToken:  string;
    refreshToken: string;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    userId:       string;
    role:         string;
    orgId:        string | null;
    accessToken:  string;
    refreshToken: string;
  }
}
