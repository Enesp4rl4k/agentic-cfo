"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  listERPIntegrations,
  connectParasut,
  syncParasut,
  disconnectParasut,
  connectLogoTiger,
  syncLogoTiger,
  syncMikro,
  getERPSyncLogs,
  deleteERPIntegration,
} from "@/lib/api/erp";
import type { ParasutConnectRequest, ERPProvider } from "@/lib/api/erp";

const INTEGRATIONS_KEY = ["erp", "integrations"] as const;
const SYNC_LOGS_KEY    = ["erp", "sync-logs"]    as const;

// ── List integrations ─────────────────────────────────────────────────────────

export function useERPIntegrations() {
  return useQuery({
    queryKey: INTEGRATIONS_KEY,
    queryFn:  listERPIntegrations,
    staleTime: 30_000,
  });
}

// ── Delete ────────────────────────────────────────────────────────────────────

export function useDeleteERPIntegration() {
  const qc = useQueryClient();
  const m  = useMutation({
    mutationFn: (id: string) => deleteERPIntegration(id),
    onSuccess:  () => qc.invalidateQueries({ queryKey: INTEGRATIONS_KEY }),
  });
  return { remove: m.mutate, loading: m.isPending, error: m.error ? String(m.error) : null };
}

// ── Paraşüt hooks ─────────────────────────────────────────────────────────────

export function useParasutConnect() {
  const m = useMutation({ mutationFn: (req: ParasutConnectRequest) => connectParasut(req) });
  return {
    result:  m.data ?? null,
    loading: m.isPending,
    error:   m.error ? String(m.error) : null,
    connect: m.mutate,
    reset:   m.reset,
  };
}

export function useParasutSync() {
  const qc = useQueryClient();
  const m  = useMutation({
    mutationFn: (integrationId: string) => syncParasut(integrationId),
    onSuccess:  () => {
      qc.invalidateQueries({ queryKey: INTEGRATIONS_KEY });
      qc.invalidateQueries({ queryKey: SYNC_LOGS_KEY });
    },
  });
  return {
    result:  m.data ?? null,
    loading: m.isPending,
    error:   m.error ? String(m.error) : null,
    sync:    m.mutate,
    reset:   m.reset,
  };
}

export function useParasutDisconnect() {
  const qc = useQueryClient();
  const m  = useMutation({
    mutationFn: (integrationId: string) => disconnectParasut(integrationId),
    onSuccess:  () => qc.invalidateQueries({ queryKey: INTEGRATIONS_KEY }),
  });
  return { disconnect: m.mutate, loading: m.isPending, error: m.error ? String(m.error) : null };
}

// ── Logo Tiger hooks ──────────────────────────────────────────────────────────

export function useLogoTigerConnect() {
  const qc = useQueryClient();
  const m  = useMutation({
    mutationFn: (displayName?: string) => connectLogoTiger(displayName),
    onSuccess:  () => qc.invalidateQueries({ queryKey: INTEGRATIONS_KEY }),
  });
  return { connect: m.mutate, loading: m.isPending, error: m.error ? String(m.error) : null };
}

export function useLogoTigerSync() {
  const qc = useQueryClient();
  const m  = useMutation({
    mutationFn: (file: File) => syncLogoTiger(file),
    onSuccess:  () => {
      qc.invalidateQueries({ queryKey: INTEGRATIONS_KEY });
      qc.invalidateQueries({ queryKey: SYNC_LOGS_KEY });
    },
  });
  return {
    result:  m.data ?? null,
    loading: m.isPending,
    error:   m.error ? String(m.error) : null,
    sync:    m.mutate,
    reset:   m.reset,
  };
}

// ── Mikro hook ────────────────────────────────────────────────────────────────

export function useMikroSync() {
  const qc = useQueryClient();
  const m  = useMutation({
    mutationFn: (file: File) => syncMikro(file),
    onSuccess:  () => {
      qc.invalidateQueries({ queryKey: INTEGRATIONS_KEY });
      qc.invalidateQueries({ queryKey: SYNC_LOGS_KEY });
    },
  });
  return {
    result:  m.data ?? null,
    loading: m.isPending,
    error:   m.error ? String(m.error) : null,
    sync:    m.mutate,
    reset:   m.reset,
  };
}

// ── Sync logs ─────────────────────────────────────────────────────────────────

export function useERPSyncLogs(provider?: ERPProvider, limit = 10) {
  return useQuery({
    queryKey: [...SYNC_LOGS_KEY, provider, limit],
    queryFn:  () => getERPSyncLogs(provider, limit),
    staleTime: 15_000,
  });
}

// ── Re-exports ────────────────────────────────────────────────────────────────

export {
  ERP_PROVIDER_LABELS,
  ERP_PROVIDER_DESCRIPTIONS,
  statusColor,
  statusBg,
  syncStatusColor,
} from "@/lib/api/erp";
