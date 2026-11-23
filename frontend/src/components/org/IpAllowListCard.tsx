"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/hooks/useI18n";
import { getIpAllowList, lockoutPreview, saveIpAllowList, type IpAllowList } from "@/lib/api/security";
import { MAX_ALLOWLIST_ENTRIES, cidrContains, parseCidr } from "@/lib/cidr";
import { isForbidden } from "@/lib/forbidden";
import { isOwner } from "@/lib/roles";

const KEY = ["ip-allowlist"] as const;

type Draft = { cidrs: string[]; enabled: boolean };

/**
 * Who may reach the company at all: the IP allow-list. The owner edits it (add and remove entries, switch it
 * on or off); an admin reads it. Saving a list that would cut the caller off (their own address is not on
 * it) or other members off is refused by the server with a preview of who would be locked out; the owner
 * then confirms explicitly or cancels, and nothing is saved until they confirm. Refusals are shown in the
 * server's own words. The system warns; the owner decides.
 */
export function IpAllowListCard() {
  const { t } = useI18n();
  const c = t.ipAllowList;
  const { data: session } = useSession();
  const owner = isOwner(session?.user?.role);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: KEY, queryFn: getIpAllowList, retry: false });

  const [draft, setDraft] = useState<Draft | null>(null);
  const [entry, setEntry] = useState("");
  const [entryError, setEntryError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lockout, setLockout] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [saved, setSaved] = useState(false);

  if (q.isLoading) return <Skeleton aria-label={c.loading} className="h-32 w-full" />;
  if (q.isError || !q.data) {
    return (
      <Card className="space-y-2 p-4">
        <h2 className="tc-display m-0 text-[20px]">{c.title}</h2>
        <p role="alert" className="m-0 text-sm text-destructive">
          {isForbidden(q.error) ? c.forbidden : c.loadFailed}
        </p>
      </Card>
    );
  }

  const stored = q.data;
  const cidrs = draft?.cidrs ?? stored.cidrs;
  const enabled = draft?.enabled ?? stored.enabled;
  const dirty = draft !== null && (draft.enabled !== stored.enabled || draft.cidrs.join(",") !== stored.cidrs.join(","));
  const callerIp = stored.caller_ip ?? null;
  const callerListed = callerIp !== null && cidrs.some((cidr) => cidrContains(cidr, callerIp));
  const needsEntry = enabled && cidrs.length === 0;
  const locked = busy || lockout !== null;

  const edit = (next: Partial<Draft>) => {
    setDraft({ cidrs, enabled, ...next });
    setSaved(false);
    setFailed(false);
    setRefusal(null);
  };

  function add(raw: string) {
    const parsed = parseCidr(raw);
    if (!parsed.ok) {
      setEntryError(parsed.reason === "invalid" ? c.errors.invalid.replace("{value}", raw.trim().slice(0, 60)) : c.errors[parsed.reason]);
      return;
    }
    if (cidrs.includes(parsed.cidr)) {
      setEntryError(c.errors.duplicate.replace("{value}", parsed.cidr));
      return;
    }
    if (cidrs.length >= MAX_ALLOWLIST_ENTRIES) {
      setEntryError(c.errors.tooMany.replace("{max}", String(MAX_ALLOWLIST_ENTRIES)));
      return;
    }
    setEntryError(null);
    setEntry("");
    edit({ cidrs: [...cidrs, parsed.cidr] });
  }

  async function save(confirmLockout: boolean) {
    setBusy(true);
    setFailed(false);
    setRefusal(null);
    try {
      const result = await saveIpAllowList({ cidrs, enabled, confirmLockout });
      const next: IpAllowList = { enabled: result.enabled, cidrs: result.cidrs, caller_ip: stored.caller_ip };
      qc.setQueryData(KEY, next);
      setDraft(null);
      setLockout(null);
      setSaved(true);
    } catch (e) {
      const preview = confirmLockout ? null : lockoutPreview(e);
      const status = (e as { status?: number } | null)?.status;
      if (preview !== null) {
        setLockout(preview);
      } else if (status && status < 500 && e instanceof Error && e.message) {
        setLockout(null);
        setRefusal(e.message); // a refusal the server explains (untrusted proxy address, bad entry, role) is shown as given
      } else {
        setLockout(null);
        setFailed(true);
      }
    } finally {
      setBusy(false);
    }
  }

  const field = "min-h-[44px] rounded-md border border-border bg-card px-3 text-sm";

  return (
    <Card className="space-y-3 p-4">
      <h2 className="tc-display m-0 text-[20px]">{c.title}</h2>
      <p className="m-0 text-sm text-muted-foreground">{c.intro}</p>
      <p className="m-0 text-sm font-medium">{stored.enabled ? c.stateOn : c.stateOff}</p>
      <p className="m-0 text-xs text-muted-foreground">
        {callerIp ? c.callerIp.replace("{ip}", callerIp) : c.callerUnknown}
      </p>
      {!owner && <p className="m-0 text-xs text-muted-foreground">{c.readOnly}</p>}

      <section aria-label={c.listTitle} className="space-y-1">
        <h3 className="m-0 text-sm font-medium">{c.listTitle}</h3>
        {cidrs.length === 0 ? (
          <p className="m-0 text-sm text-muted-foreground">{c.listEmpty}</p>
        ) : (
          <ul className="m-0 list-none space-y-1 p-0">
            {cidrs.map((cidr) => (
              <li key={cidr} className="flex items-center justify-between gap-2 text-sm">
                <code>{cidr}</code>
                {owner && (
                  <Button
                    variant="outline"
                    className="min-h-[44px]"
                    disabled={locked}
                    aria-label={c.removeLabel.replace("{cidr}", cidr)}
                    onClick={() => edit({ cidrs: cidrs.filter((x) => x !== cidr) })}
                  >
                    {c.remove}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {owner && (
        <div className="space-y-3">
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              add(entry);
            }}
          >
            <label className="flex min-w-[220px] flex-1 flex-col gap-1 text-sm">
              {c.addLabel}
              <input
                value={entry}
                disabled={locked}
                onChange={(e) => {
                  setEntry(e.target.value);
                  setEntryError(null);
                }}
                placeholder={c.addPlaceholder}
                aria-invalid={entryError ? true : undefined}
                aria-describedby={entryError ? "ip-allowlist-entry-error" : undefined}
                className={field}
              />
            </label>
            <Button type="submit" variant="outline" className="min-h-[44px]" disabled={locked || entry.trim() === ""}>
              {c.add}
            </Button>
            {callerIp && !callerListed && (
              <Button type="button" variant="outline" className="min-h-[44px]" disabled={locked} onClick={() => add(callerIp)}>
                {c.addMine.replace("{ip}", callerIp)}
              </Button>
            )}
          </form>
          {entryError && (
            <p id="ip-allowlist-entry-error" role="alert" className="m-0 text-sm text-destructive">
              {entryError}
            </p>
          )}

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              role="switch"
              checked={enabled}
              disabled={locked}
              onChange={(e) => edit({ enabled: e.target.checked })}
            />
            {c.toggleLabel}
          </label>
          {needsEntry && <p className="m-0 text-xs text-destructive">{c.needEntry}</p>}

          {lockout !== null && (
            <div role="alert" className="space-y-2 rounded-md border border-destructive p-3">
              <p className="m-0 text-sm font-semibold">{c.lockout.title}</p>
              <p className="m-0 text-xs text-muted-foreground">{c.lockout.intro}</p>
              <p className="m-0 text-sm">{lockout}</p>
              <p className="m-0 text-xs text-muted-foreground">{c.lockout.hint}</p>
              <div className="flex flex-wrap gap-2">
                <Button className="min-h-[44px]" variant="destructive" disabled={busy} onClick={() => void save(true)}>
                  {c.lockout.confirm}
                </Button>
                <Button className="min-h-[44px]" variant="outline" disabled={busy} onClick={() => setLockout(null)}>
                  {c.lockout.cancel}
                </Button>
              </div>
            </div>
          )}

          {refusal !== null && (
            <div role="alert" className="space-y-1 rounded-md border border-destructive p-3">
              <p className="m-0 text-sm font-semibold">{c.refusedTitle}</p>
              <p className="m-0 text-sm">{refusal}</p>
            </div>
          )}
          {failed && <p role="alert" className="m-0 text-sm text-destructive">{c.saveFailed}</p>}
          {saved && <p role="status" className="m-0 text-sm text-success">{c.saved}</p>}

          <div className="flex flex-wrap items-center gap-2">
            <Button className="min-h-[44px]" disabled={!dirty || needsEntry || locked} onClick={() => void save(false)}>
              {busy ? c.saving : c.save}
            </Button>
            {dirty && (
              <>
                <Button variant="outline" className="min-h-[44px]" disabled={locked} onClick={() => { setDraft(null); setEntryError(null); setRefusal(null); }}>
                  {c.revert}
                </Button>
                <span className="text-xs text-muted-foreground">{c.unsaved}</span>
              </>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}
