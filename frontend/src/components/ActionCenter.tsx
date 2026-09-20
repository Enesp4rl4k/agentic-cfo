"use client";

import { useEffect, useState } from "react";
import { getPendingActions, approveAction, rejectAction, PendingAction } from "@/lib/api/actions";
import { Check, X, Zap, AlertCircle } from "lucide-react";

export function ActionCenter() {
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
      await approveAction(id);
      setActions((prev) => prev.filter((a) => a.id !== id));
    } catch (err: any) {
      alert(`Onay başarısız: ${err.message}`);
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
      alert(`Red başarısız: ${err.message}`);
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
                onClick={() => handleApprove(action.id)}
                disabled={processingId === action.id}
                className="flex-1 inline-flex justify-center items-center rounded-md bg-green-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-green-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-green-600 disabled:opacity-50"
              >
                {processingId === action.id ? "İşleniyor..." : (
                  <>
                    <Check className="w-4 h-4 mr-1.5" />
                    Onayla
                  </>
                )}
              </button>
              <button
                onClick={() => handleReject(action.id)}
                disabled={processingId === action.id}
                className="flex-none inline-flex items-center rounded-md bg-secondary px-3 py-2 text-sm font-semibold text-secondary-foreground shadow-sm hover:bg-secondary/80 disabled:opacity-50"
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
