"use client";

import { useEffect, useState } from "react";
import { getPendingActions, approveAction, rejectAction, PendingAction } from "@/lib/api/actions";
import { Check, X, Zap, AlertCircle } from "lucide-react";
import { useCan } from "@/hooks/useCan";
import { useI18n } from "@/hooks/useI18n";
import { isForbidden } from "@/lib/forbidden";

export function ActionCenter() {
  const { t } = useI18n();
  const can = useCan("decide");
  const refused = (err: Error) => err.message || t.roleGate.forbidden;
  const [notice, setNotice] = useState<string | null>(null);
  const [actions, setActions] = useState<PendingAction[]>([]);
  const [loading, setLoading] = useState(true);
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchActions();
  }, []);

  const fetchActions = async () => {
    try {
      setLoading(true);
      const data = await getPendingActions();
      setActions(data);
      setError(null);
    } catch (err: any) {
      setError(err.message || "Aksiyonlar yüklenemedi.");
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async (id: string) => {
    try {
      setProcessingId(id);
      setNotice(null);
      await approveAction(id);
      setActions((prev) => prev.filter((a) => a.id !== id));
    } catch (err: any) {
      // 501: no connector exists for this action; nothing ran, so it stays in the list.
      if (err?.status === 501) setNotice(t.onay.actionNotConnected);
      else if (isForbidden(err)) setNotice(refused(err));
      else alert(`Onay başarısız: ${err.message}`);
    } finally {
      setProcessingId(null);
    }
  };

  const handleReject = async (id: string) => {
    try {
      setProcessingId(id);
      await rejectAction(id);
      setActions((prev) => prev.filter((a) => a.id !== id));
    } catch (err: any) {
      if (isForbidden(err)) setNotice(refused(err));
      else alert(`Red başarısız: ${err.message}`);
    } finally {
      setProcessingId(null);
    }
  };

  if (loading) {
    return <div className="p-4 text-sm text-muted-foreground animate-pulse">Aksiyonlar kontrol ediliyor...</div>;
  }

  if (error) {
    return (
      <div className="p-4 flex items-center text-red-500 bg-red-500/10 rounded-lg">
        <AlertCircle className="w-5 h-5 mr-2" />
        {error}
      </div>
    );
  }

  if (actions.length === 0) {
    return null; // Don't show anything if no actions are pending
  }

  return (
    <div className="space-y-4 mb-8">
      <div className="flex items-center space-x-2">
        <Zap className="w-5 h-5 text-yellow-500" />
        <h2 className="text-lg font-semibold tracking-tight">Onay Bekleyen Otonom Aksiyonlar</h2>
        <span className="bg-yellow-500/20 text-yellow-600 dark:text-yellow-400 text-xs font-medium px-2 py-0.5 rounded-full">
          {actions.length} Bekleyen
        </span>
      </div>

      {notice && (
        <div role="status" className="flex items-center text-amber-600 bg-amber-500/10 rounded-lg p-3 text-sm">
          <AlertCircle className="w-4 h-4 mr-2" />
          {notice}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {actions.map((action) => (
          <div key={action.id} className="relative group overflow-hidden rounded-xl border border-border bg-card p-5 shadow-sm transition-all hover:shadow-md">
            <div className="flex items-start justify-between">
              <div>
                <span className="inline-flex items-center rounded-md bg-primary/10 px-2 py-1 text-xs font-medium text-primary ring-1 ring-inset ring-primary/20 mb-3">
                  {action.responsible_agent.toUpperCase()} Agent
                </span>
              </div>
            </div>
            
            <p className="text-sm font-medium mb-5 text-card-foreground">
              {action.description}
            </p>

            <div className="flex items-center space-x-3 mt-auto">
              <button
                onClick={can.allowed ? () => handleApprove(action.id) : undefined}
                disabled={processingId === action.id}
                aria-disabled={can.allowed ? undefined : true}
                title={can.reason ?? undefined}
                className="flex-1 inline-flex justify-center items-center rounded-md bg-green-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-green-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-green-600 disabled:opacity-50 aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
              >
                {processingId === action.id ? "İşleniyor..." : (
                  <>
                    <Check className="w-4 h-4 mr-1.5" />
                    Onayla
                  </>
                )}
              </button>
              <button
                onClick={can.allowed ? () => handleReject(action.id) : undefined}
                disabled={processingId === action.id}
                aria-disabled={can.allowed ? undefined : true}
                title={can.reason ?? undefined}
                aria-label="Reddet"
                className="flex-none inline-flex items-center rounded-md bg-secondary px-3 py-2 text-sm font-semibold text-secondary-foreground shadow-sm hover:bg-secondary/80 disabled:opacity-50 aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
