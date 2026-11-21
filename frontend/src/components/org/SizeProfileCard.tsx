"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { useOrgSettings } from "@/hooks/useOrgSettings";
import {
  confirmSizeProfile, getSizeProfile, saveSizeAnswers, setFocusMode,
  type SizeOption, type SizeProfile, type SizeProfileState,
} from "@/lib/api/sizeProfile";

const KEY = ["size-profile"] as const;
const PROFILES: SizeProfile[] = ["micro", "small", "medium"];

type Draft = { outflow: string; headcount: string; inhouse: string };
const EMPTY: Draft = { outflow: "", headcount: "", inhouse: "" };

const draftOf = (s: SizeProfileState): Draft => ({
  outflow: s.monthly_outflow_band ?? "",
  headcount: s.headcount_band ?? "",
  inhouse: s.has_inhouse_finance == null ? "" : s.has_inhouse_finance ? "yes" : "no",
});

function Question({
  legend, name, options, value, onChange,
}: { legend: string; name: string; options: SizeOption[]; value: string; onChange: (v: string) => void }) {
  return (
    <fieldset className="space-y-1.5">
      <legend className="text-sm font-medium">{legend}</legend>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {options.map((o) => (
          <label key={o.value} className="flex min-h-[32px] cursor-pointer items-center gap-2 text-sm">
            <input
              type="radio" name={name} value={o.value} checked={value === o.value}
              onChange={() => onChange(o.value)}
            />
            {o.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/**
 * One short, skippable question group about the company's size, and the profile it suggests.
 *
 * The system proposes, the person decides: answering stores the answers and shows the suggested
 * profile with the answer that decided it; only "Onayla" stores the profile. Skipping calls nothing,
 * so everything stays as it was. The server answers 403 to anyone but an owner or admin; then the
 * card renders nothing.
 */
export function SizeProfileCard() {
  const { t } = useI18n();
  const sp = t.sizeProfile;
  const { refresh } = useOrgSettings();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: KEY, queryFn: getSizeProfile, retry: false });
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [editing, setEditing] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [pending, setPending] = useState<SizeProfileState | null>(null);
  const [chosen, setChosen] = useState<SizeProfile | null>(null);
  const [notice, setNotice] = useState<"simplified" | "restored" | "saved" | null>(null);
  const [failed, setFailed] = useState(false);

  if (!data) return null;
  const name = (p: SizeProfile) => sp.profiles[p];
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  async function guarded(action: () => Promise<void>) {
    setFailed(false);
    try {
      await action();
    } catch {
      setFailed(true);
    }
  }

  const submit = () => {
    if (!draft.outflow && !draft.headcount && !draft.inhouse) {
      setDismissed(true); // nothing answered is the same as skipping
      return;
    }
    void guarded(async () => {
      const next = await saveSizeAnswers({
        monthly_outflow_band: draft.outflow || null,
        headcount_band: draft.headcount || null,
        has_inhouse_finance: draft.inhouse ? draft.inhouse === "yes" : null,
      });
      qc.setQueryData(KEY, next);
      setEditing(false);
      if (next.suggestion) {
        setPending(next);
        setChosen(next.suggestion.profile);
      } else {
        setNotice("saved");
      }
    });
  };

  const confirm = () => {
    if (!chosen) return;
    void guarded(async () => {
      const next = await confirmSizeProfile(chosen);
      qc.setQueryData(KEY, next);
      setPending(null);
      setNotice(next.focus_mode_changed && next.focus_mode ? "simplified" : "saved");
      await refresh();
    });
  };

  const undo = () =>
    void guarded(async () => {
      await setFocusMode(false);
      setNotice("restored");
      await refresh();
    });

  const suggestion = pending?.suggestion;
  if (pending && suggestion && chosen) {
    return (
      <Card className="space-y-3 p-4" aria-live="polite">
        <h2 className="tc-display m-0 text-[20px]">{sp.suggestion.title.replace("{profile}", name(suggestion.profile))}</h2>
        <p className="m-0 text-sm text-muted-foreground">
          {suggestion.decided_by === "volume" ? sp.suggestion.byVolume : sp.suggestion.byHeadcount}
          {suggestion.disagreement && ` ${sp.suggestion.disagreement}`}
        </p>
        <label className="flex items-center gap-2 text-sm">
          {sp.suggestion.other}
          <select
            className="rounded border border-input bg-background px-2 py-1 text-sm"
            value={chosen} onChange={(e) => setChosen(e.target.value as SizeProfile)}
          >
            {PROFILES.map((p) => <option key={p} value={p}>{name(p)}</option>)}
          </select>
        </label>
        {failed && <p role="alert" className="m-0 text-sm text-destructive">{sp.error}</p>}
        <Button className="min-h-[44px]" onClick={confirm}>{sp.suggestion.confirm}</Button>
      </Card>
    );
  }

  if (!editing && (data.size_profile || notice)) {
    return (
      <Card className="space-y-2 p-4" aria-live="polite">
        {data.size_profile && (
          <p className="m-0 text-sm font-medium">{sp.summary.current.replace("{profile}", name(data.size_profile))}</p>
        )}
        {notice === "simplified" && (
          <p className="m-0 flex flex-wrap items-center gap-3 text-sm">
            {sp.menu.simplified}
            <Button size="sm" variant="outline" onClick={undo}>{sp.menu.undo}</Button>
          </p>
        )}
        {notice === "restored" && <p className="m-0 text-sm">{sp.menu.restored}</p>}
        {notice === "saved" && <p className="m-0 text-sm">{sp.saved}</p>}
        {failed && <p role="alert" className="m-0 text-sm text-destructive">{sp.error}</p>}
        <Button size="sm" variant="ghost" onClick={() => { setDraft(draftOf(data)); setEditing(true); setNotice(null); }}>{sp.summary.edit}</Button>
      </Card>
    );
  }

  if (dismissed && !editing) return null;

  const yesNo: SizeOption[] = [{ value: "yes", label: sp.yes }, { value: "no", label: sp.no }];
  return (
    <Card className="space-y-4 p-4">
      <div className="space-y-1">
        <h2 className="tc-display m-0 text-[20px]">{sp.title}</h2>
        <p className="m-0 text-sm text-muted-foreground">{sp.reason}</p>
        <p className="m-0 text-xs text-muted-foreground">{sp.safety}</p>
      </div>
      <Question
        legend={sp.questions.outflow} name="size-outflow" options={data.options.monthly_outflow_band}
        value={draft.outflow} onChange={(v) => set({ outflow: v })}
      />
      <Question
        legend={sp.questions.headcount} name="size-headcount" options={data.options.headcount_band}
        value={draft.headcount} onChange={(v) => set({ headcount: v })}
      />
      <Question
        legend={sp.questions.inhouse} name="size-inhouse" options={yesNo}
        value={draft.inhouse} onChange={(v) => set({ inhouse: v })}
      />
      {failed && <p role="alert" className="m-0 text-sm text-destructive">{sp.error}</p>}
      <div className="flex flex-wrap gap-2">
        <Button className="min-h-[44px]" onClick={submit}>{sp.next}</Button>
        <Button className="min-h-[44px]" variant="ghost" onClick={() => { setDismissed(true); setEditing(false); }}>
          {sp.skip}
        </Button>
      </div>
    </Card>
  );
}
