"use client";

import { useCallback, useEffect, useState } from "react";
import { Github, RefreshCw, Plug, CheckCircle2, AlertTriangle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { CanButton } from "@/components/ui/can-button";
import { useCan } from "@/hooks/useCan";
import { useI18n } from "@/hooks/useI18n";
import { failureMessage } from "@/lib/forbidden";
import {
  listConnectors,
  connectConnector,
  syncConnector,
  type ConnectorStatus,
} from "@/lib/api/connectors";

/**
 * GitHub connector control for the CTO view (Faz 13).
 * Connect once, then "Sync now" pulls commits/PRs/issues into canonical storage
 * and re-runs the CTO kernel — which flips its provenance badge to "Bağlı veri".
 */
export function GitHubConnectorCard({ onSynced }: { onSynced?: () => void }) {
  const { t } = useI18n();
  const decide = useCan("decide");
  const [status, setStatus] = useState<ConnectorStatus | null>(null);
  const [owner, setOwner] = useState("");
  const [repo, setRepo] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const all = await listConnectors();
      setStatus(all.find((c) => c.name === "github") ?? null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "durum alınamadı");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const connect = useCallback(async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const r = await connectConnector("github", {
        config: { owner, repo },
        secret: { token },
      });
      setMsg(`Bağlandı: ${r.account ?? "?"} — ${r.detail}`);
      setToken("");
      await refresh();
    } catch (e) {
      setErr(failureMessage(e, "bağlantı başarısız", t.roleGate.forbidden));
    } finally {
      setBusy(false);
    }
  }, [owner, repo, token, refresh, t.roleGate.forbidden]);

  const sync = useCallback(async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const r = await syncConnector("github", true);
      setMsg(
        `${r.sync.records_written} sinyal işlendi` +
          (r.sync.warnings.length ? ` · ${r.sync.warnings.join("; ")}` : "")
      );
      await refresh();
      onSynced?.();
    } catch (e) {
      setErr(failureMessage(e, "sync başarısız", t.roleGate.forbidden));
    } finally {
      setBusy(false);
    }
  }, [refresh, onSynced, t.roleGate.forbidden]);

  const connected = status?.connected ?? false;

  return (
    <div className="rounded-xl border border-border bg-card/50 p-4">
      <div className="mb-3 flex items-center gap-2">
        <Github className="h-4 w-4" />
        <span className="text-sm font-semibold">GitHub bağlantısı</span>
        {connected ? (
          <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
            <CheckCircle2 className="h-3.5 w-3.5" /> bağlı
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">bağlı değil — CTO metrikleri tahmini</span>
        )}
      </div>

      {connected ? (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="text-muted-foreground">
            Son sync:{" "}
            {status?.last_sync_at
              ? new Date(status.last_sync_at).toLocaleString("tr-TR")
              : "—"}
            {status?.last_record_count != null && ` · ${status.last_record_count} kayıt`}
          </span>
          <CanButton action="edit" onClick={sync} disabled={busy} variant="outline" className="ml-auto gap-2">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Şimdi senkronize et
          </CanButton>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <input
            value={owner}
            onChange={(e) => setOwner(e.target.value)}
            placeholder="owner (org/kullanıcı)"
            disabled={!decide.allowed}
            className="rounded-md border bg-background px-3 py-2 text-sm"
          />
          <input
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            placeholder="repo"
            disabled={!decide.allowed}
            className="rounded-md border bg-background px-3 py-2 text-sm"
          />
          <input
            value={token}
            onChange={(e) => setToken(e.target.value)}
            type="password"
            placeholder="Personal Access Token"
            disabled={!decide.allowed}
            className="rounded-md border bg-background px-3 py-2 text-sm"
          />
          <CanButton
            action="decide"
            onClick={connect}
            disabled={busy || !owner || !repo || !token}
            className="gap-2 sm:col-span-3"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plug className="h-4 w-4" />}
            Bağlan ve doğrula
          </CanButton>
        </div>
      )}

      {msg && <p className="mt-2 text-xs text-emerald-400">{msg}</p>}
      {(err || status?.last_error) && (
        <p className="mt-2 flex items-center gap-1 text-xs text-red-400">
          <AlertTriangle className="h-3.5 w-3.5" /> {err || status?.last_error}
        </p>
      )}
    </div>
  );
}
