"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
} from "react";
import { useRouter } from "next/navigation";
import { apiClient } from "@/lib/api/client";

export interface AuthUser {
  id: string;
  email: string;
  full_name: string;
  role: string;
  organization: {
    id: string;
    name: string;
    slug: string;
    plan: string;
  };
}

interface AuthContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

// Inject access token into every request
function setupInterceptor(getToken: () => string | null) {
  apiClient.interceptors.request.use((config) => {
    const token = getToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  });
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [accessToken, setAccessToken] = useState<string | null>(null);

  // Keep token in a ref-like closure for the interceptor
  const getToken = useCallback(() => {
    if (accessToken) return accessToken;
    if (typeof window !== "undefined") {
      return localStorage.getItem("access_token");
    }
    return null;
  }, [accessToken]);

  // Set up axios interceptor once
  useEffect(() => {
    setupInterceptor(getToken);
  }, [getToken]);

  // On mount: try to load user from stored token
  useEffect(() => {
    const init = async () => {
      const storedToken = typeof window !== "undefined"
        ? localStorage.getItem("access_token")
        : null;

      if (!storedToken) {
        setIsLoading(false);
        return;
      }

      setAccessToken(storedToken);
      try {
        const res = await apiClient.get<{ data: AuthUser; error: null }>("/auth/me", {
          headers: { Authorization: `Bearer ${storedToken}` },
        });
        setUser(res.data.data);
        // Set session indicator cookie for middleware
        document.cookie = "_session=1; path=/; SameSite=Lax";
      } catch {
        // Token invalid — clear it
        localStorage.removeItem("access_token");
        setAccessToken(null);
        document.cookie = "_session=; path=/; max-age=0";
      } finally {
        setIsLoading(false);
      }
    };
    init();
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await apiClient.post<{
      data: { access_token: string; user: AuthUser };
      error: null;
    }>("/auth/login", { email, password });

    const token = res.data.data.access_token;
    setAccessToken(token);
    setUser(res.data.data.user);
    if (typeof window !== "undefined") {
      localStorage.setItem("access_token", token);
    }
    document.cookie = "_session=1; path=/; SameSite=Lax";
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiClient.post("/auth/logout");
    } catch {
      // ignore
    }
    setAccessToken(null);
    setUser(null);
    if (typeof window !== "undefined") {
      localStorage.removeItem("access_token");
    }
    document.cookie = "_session=; path=/; max-age=0";
    router.push("/login");
  }, [router]);

  const refresh = useCallback(async (): Promise<boolean> => {
    try {
      const res = await apiClient.post<{
        data: { access_token: string };
        error: null;
      }>("/auth/refresh");
      const token = res.data.data.access_token;
      setAccessToken(token);
      if (typeof window !== "undefined") {
        localStorage.setItem("access_token", token);
      }
      return true;
    } catch {
      await logout();
      return false;
    }
  }, [logout]);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        login,
        logout,
        refresh,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
