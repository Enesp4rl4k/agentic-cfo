"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider, useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import { ToastProvider } from "@/components/ui/toast";
import { ThemeProvider } from "@/components/ui/theme-toggle";
import { CompanyContextProvider, useCompanyContextStore } from "@/store/companyContext";

/**
 * OrgIdSync — bridges NextAuth session orgId into the CompanyContext store.
 *
 * Must be rendered *inside* both SessionProvider and CompanyContextProvider.
 * Runs on every session change and syncs orgId silently — no UI rendered.
 */
function OrgIdSync() {
  const { data: session } = useSession();
  const { setOrgId, orgId: storeOrgId } = useCompanyContextStore();

  useEffect(() => {
    const sessionOrgId = session?.user?.orgId ?? null;
    // Only call setOrgId when the value actually changes to avoid loops
    if (sessionOrgId !== storeOrgId) {
      setOrgId(sessionOrgId);
    }
  }, [session?.user?.orgId, storeOrgId, setOrgId]);

  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
          },
        },
      })
  );

  return (
    <SessionProvider>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <CompanyContextProvider>
            {/* Sync session orgId → store (no UI, effect only) */}
            <OrgIdSync />
            <ToastProvider>{children}</ToastProvider>
          </CompanyContextProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </SessionProvider>
  );
}
