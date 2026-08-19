"use client";
/**
 * Company Context Store — lightweight React Context + localStorage.
 *
 * No Zustand dependency needed. Stores the active CFO job ID and
 * company name so all dashboard pages share the same context without
 * relying on URL query params.
 *
 * Usage:
 *   const { activeCFOJobId, setActiveCFOJob } = useCompanyContextStore();
 */
import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";

const STORAGE_KEY = "aicfo:workspace";

interface WorkspaceState {
  activeCFOJobId: string | null;
  companyName: string | null;
  reportingPeriod: string | null;
  orgId: string | null;
}

interface CompanyContextStoreValue extends WorkspaceState {
  setActiveCFOJob: (jobId: string, companyName?: string, period?: string) => void;
  setCompanyName: (name: string) => void;
  /** Sync orgId from NextAuth session — called by OrgIdSync in providers.tsx */
  setOrgId: (orgId: string | null) => void;
  clearWorkspace: () => void;
}

const defaultState: WorkspaceState = {
  activeCFOJobId: null,
  companyName: null,
  reportingPeriod: null,
  orgId: null,
};

const CompanyContextStore = createContext<CompanyContextStoreValue>({
  ...defaultState,
  setActiveCFOJob: () => {},
  setCompanyName: () => {},
  setOrgId: () => {},
  clearWorkspace: () => {},
});

function loadFromStorage(): WorkspaceState {
  if (typeof window === "undefined") return defaultState;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultState;
    return { ...defaultState, ...JSON.parse(raw) };
  } catch {
    return defaultState;
  }
}

function saveToStorage(state: WorkspaceState): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignore quota errors
  }
}

export function CompanyContextProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<WorkspaceState>(defaultState);

  // Load from localStorage on mount
  useEffect(() => {
    setState(loadFromStorage());
  }, []);

  const setActiveCFOJob = useCallback(
    (jobId: string, companyName?: string, period?: string) => {
      setState((prev) => {
        const next: WorkspaceState = {
          ...prev,
          activeCFOJobId: jobId,
          companyName: companyName ?? prev.companyName,
          reportingPeriod: period ?? prev.reportingPeriod,
        };
        saveToStorage(next);
        return next;
      });
    },
    []
  );

  const setCompanyName = useCallback((name: string) => {
    setState((prev) => {
      const next = { ...prev, companyName: name };
      saveToStorage(next);
      return next;
    });
  }, []);

  /**
   * Sync the org ID from NextAuth session into the workspace store.
   * Called by OrgIdSync (in providers.tsx) whenever the session changes.
   * Only persists to localStorage when orgId actually changes to avoid
   * triggering unnecessary re-renders.
   */
  const setOrgId = useCallback((orgId: string | null) => {
    setState((prev) => {
      if (prev.orgId === orgId) return prev; // no-op if unchanged
      const next = { ...prev, orgId };
      saveToStorage(next);
      return next;
    });
  }, []);

  const clearWorkspace = useCallback(() => {
    if (typeof window !== "undefined") {
      localStorage.removeItem(STORAGE_KEY);
    }
    setState(defaultState);
  }, []);

  return (
    <CompanyContextStore.Provider
      value={{ ...state, setActiveCFOJob, setCompanyName, setOrgId, clearWorkspace }}
    >
      {children}
    </CompanyContextStore.Provider>
  );
}

export function useCompanyContextStore(): CompanyContextStoreValue {
  return useContext(CompanyContextStore);
}
