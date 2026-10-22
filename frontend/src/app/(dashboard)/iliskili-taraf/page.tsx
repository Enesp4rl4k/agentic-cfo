"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Plus, Search, Trash2, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import type { MessageTree } from "@/lib/i18n";
import {
  checkCounterparty,
  createRelatedParty,
  deactivateRelatedParty,
  fetchCounterpartySuggestions,
  listRelatedParties,
  type CounterpartySuggestion,
  type PartyMatch,
  type RelatedParty,
  type RelationshipType,
} from "@/lib/api/relatedParty";

const RELATIONSHIP_ORDER: RelationshipType[] = [
  "ortak",
  "yonetici",
  "aile",
  "istirak",
  "ana_ortaklik",
  "kilit_personel",
  "diger",
];

// Backend keys → message-tree keys (the tree uses camelCase section names).
const REL_KEY: Record<
  RelationshipType,
  keyof MessageTree["iliskiliTaraf"]["relationships"]
> = {
  ortak: "ortak",
  yonetici: "yonetici",
  aile: "aile",
  istirak: "istirak",
  ana_ortaklik: "anaOrtaklik",
  kilit_personel: "kilitPersonel",
  diger: "diger",
};

const MATCH_KEY: Record<
  PartyMatch["matched_on"],
  keyof MessageTree["iliskiliTaraf"]["matchedOn"]
> = {
  tax_id: "taxId",
  exact_name: "exactName",
  name_in_text: "nameInText",
};

// ── Suggestions ───────────────────────────────────────────────────────────────
// This is the top of the page rather than a sidebar, because an empty register
// flags nothing and nobody lists their own related parties from memory. The
// question the page asks is not "who are your related parties" but "here are the
// counterparties you actually pay — which of these are you connected to?".

function SuggestionRow({
  suggestion,
  onAdd,
  busy,
}: {
  suggestion: CounterpartySuggestion;
  onAdd: (name: string, rel: RelationshipType) => Promise<void>;
  busy: boolean;
}) {
  const [rel, setRel] = useState<RelationshipType>("ortak");
  const { t } = useI18n();
  const it = t.iliskiliTaraf;
  const fmt = useCurrencyFormat();

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-border/50 py-2.5 last:border-0">
      <div className="min-w-[180px] flex-1">
        <div className="truncate text-sm font-medium">{suggestion.vendor}</div>
        <div className="text-xs text-muted-foreground">
          {it.suggestions.row
            .replace("{count}", String(suggestion.transaction_count))
            .replace("{amount}", fmt(suggestion.total_kurus / 100))}
        </div>
      </div>
      <select
        aria-label={it.suggestions.addAria.replace("{name}", suggestion.vendor)}
        value={rel}
        onChange={(e) => setRel(e.target.value as RelationshipType)}
        className="h-8 rounded-md border border-border bg-background px-2 text-xs"
      >
        {RELATIONSHIP_ORDER.map((r) => (
          <option key={r} value={r}>
            {it.relationships[REL_KEY[r]]}
          </option>
        ))}
      </select>
      <Button
        size="sm"
        variant="outline"
        disabled={busy}
        onClick={() => onAdd(suggestion.vendor, rel)}
        className="gap-1.5"
      >
        <Plus className="h-3.5 w-3.5" />
        {it.suggestions.add}
      </Button>
    </div>
  );
}

// ── Check ─────────────────────────────────────────────────────────────────────

function CheckPanel({ registrySize }: { registrySize: number }) {
  const [text, setText] = useState("");
  const [result, setResult] = useState<{ flagged: boolean; match: PartyMatch | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const { t } = useI18n();
  const it = t.iliskiliTaraf;
  const check = it.check;

  const run = useCallback(async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      const r = await checkCounterparty({ vendor: text, description: text });
      setResult({ flagged: r.is_related_party, match: r.match });
    } finally {
      setBusy(false);
    }
  }, [text]);

  return (
    <Card className="space-y-3 p-4">
      <div>
        <div className="text-sm font-medium">{check.heading}</div>
        <p className="mt-0.5 text-xs text-muted-foreground">{check.body}</p>
      </div>
      <div className="flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder={check.placeholder}
          className="h-9 flex-1 rounded-md border border-border bg-background px-3 text-sm"
        />
        <Button onClick={run} disabled={busy || !text.trim()} variant="outline" className="gap-1.5">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          {check.try}
        </Button>
      </div>

      {result && (
        <div
          className={cn(
            "rounded-md border px-3 py-2 text-sm",
            result.flagged
              ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
              : "border-border bg-muted/30 text-muted-foreground",
          )}
        >
          {result.flagged && result.match ? (
            <>
              <span className="font-medium">{result.match.party_name}</span>{" "}
              {check.matched.replace(
                "{relationship}",
                it.relationships[REL_KEY[result.match.relationship_type]],
              )}
              <div className="mt-0.5 text-xs opacity-80">
                {check.basis.replace("{basis}", it.matchedOn[MATCH_KEY[result.match.matched_on]])} · <code>{result.match.matched_value}</code>. {check.basisNote}
              </div>
            </>
          ) : (
            <>
              {check.noMatch}
              {registrySize === 0 && <> {check.registryEmpty}</>}
            </>
          )}
        </div>
      )}
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function RelatedPartyPage() {
  const [parties, setParties] = useState<RelatedParty[]>([]);
  const [suggestions, setSuggestions] = useState<CounterpartySuggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [newName, setNewName] = useState("");
  const [newRel, setNewRel] = useState<RelationshipType>("ortak");

  const { t } = useI18n();
  const it = t.iliskiliTaraf;

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [reg, sug] = await Promise.all([
        listRelatedParties(),
        fetchCounterpartySuggestions(),
      ]);
      setParties(reg.parties);
      setSuggestions(sug.suggestions);
    } catch (e) {
      setErr(e instanceof Error ? e.message : it.errors.load);
    } finally {
      setLoading(false);
    }
  }, [it]);

  useEffect(() => {
    load();
  }, [load]);

  const add = useCallback(
    async (name: string, rel: RelationshipType) => {
      setBusy(true);
      setErr(null);
      try {
        await createRelatedParty({ name, relationship_type: rel });
        setNewName("");
        await load();
      } catch (e) {
        setErr(e instanceof Error ? e.message : it.errors.add);
      } finally {
        setBusy(false);
      }
    },
    [load, it],
  );

  const remove = useCallback(
    async (id: string) => {
      setBusy(true);
      try {
        await deactivateRelatedParty(id);
        await load();
      } catch (e) {
        setErr(e instanceof Error ? e.message : it.errors.remove);
      } finally {
        setBusy(false);
      }
    },
    [load, it],
  );

  const byType = useMemo(() => {
    const groups = new Map<RelationshipType, RelatedParty[]>();
    for (const p of parties) {
      const list = groups.get(p.relationship_type) ?? [];
      list.push(p);
      groups.set(p.relationship_type, list);
    }
    return RELATIONSHIP_ORDER.filter((r) => groups.has(r)).map((r) => ({
      type: r,
      items: groups.get(r)!,
    }));
  }, [parties]);

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">{it.title}</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{it.subtitle}</p>
      </div>

      {err && (
        <Card className="border-red-500/40 bg-red-500/5 p-3 text-sm text-red-400">{err}</Card>
      )}

      {loading ? (
        <Card className="p-8 text-center text-sm text-muted-foreground">
          <Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin" />
          {it.loading}
        </Card>
      ) : (
        <>
          {/* Suggestions lead, because an empty register does nothing. */}
          {suggestions.length > 0 && (
            <Card className="space-y-1 p-4">
              <div className="text-sm font-medium">{it.suggestions.heading}</div>
              <p className="pb-1 text-xs text-muted-foreground">{it.suggestions.body}</p>
              {suggestions.map((s) => (
                <SuggestionRow
                  key={s.normalized_name}
                  suggestion={s}
                  onAdd={add}
                  busy={busy}
                />
              ))}
            </Card>
          )}

          {/* Register */}
          <Card className="space-y-4 p-4">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Users className="h-4 w-4 text-primary" />
              {it.register.heading}
              <span className="text-xs font-normal text-muted-foreground">
                {it.register.count.replace("{count}", String(parties.length))}
              </span>
            </div>

            <div className="flex flex-wrap gap-2">
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && newName.trim() && add(newName, newRel)}
                placeholder={it.register.namePlaceholder}
                className="h-9 min-w-[200px] flex-1 rounded-md border border-border bg-background px-3 text-sm"
              />
              <select
                aria-label={it.register.relationshipAria}
                value={newRel}
                onChange={(e) => setNewRel(e.target.value as RelationshipType)}
                className="h-9 rounded-md border border-border bg-background px-2 text-sm"
              >
                {RELATIONSHIP_ORDER.map((r) => (
                  <option key={r} value={r}>
                    {it.relationships[REL_KEY[r]]}
                  </option>
                ))}
              </select>
              <Button
                onClick={() => add(newName, newRel)}
                disabled={busy || !newName.trim()}
                className="gap-1.5"
              >
                <Plus className="h-4 w-4" />
                {it.register.add}
              </Button>
            </div>

            {parties.length === 0 ? (
              <p className="py-4 text-center text-sm text-muted-foreground">{it.register.empty}</p>
            ) : (
              <div className="space-y-3">
                {byType.map(({ type, items }) => (
                  <div key={type}>
                    <div className="mb-1 text-xs font-medium tracking-wide text-muted-foreground">
                      {it.relationships[REL_KEY[type]].toUpperCase()}
                    </div>
                    {items.map((p) => (
                      <div
                        key={p.id}
                        className="flex items-center gap-3 border-b border-border/50 py-2 last:border-0"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm">{p.name}</div>
                          <div className="text-xs text-muted-foreground">
                            {it.register.matchKey} <code>{p.normalized_name}</code>
                            {p.tax_id && <> · {it.register.taxId} {p.tax_id}</>}
                          </div>
                        </div>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={busy}
                          onClick={() => remove(p.id)}
                          aria-label={it.register.removeAria.replace("{name}", p.name)}
                          className="gap-1.5 text-muted-foreground hover:text-red-400"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          {it.register.remove}
                        </Button>
                      </div>
                    ))}
                  </div>
                ))}
                <p className="pt-1 text-xs text-muted-foreground">{it.register.footnote}</p>
              </div>
            )}
          </Card>

          <CheckPanel registrySize={parties.length} />
        </>
      )}
    </div>
  );
}
