"use client";

import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/hooks/useI18n";

/**
 * The login panel's one authored moment: how a decision is made here.
 *
 * Company data (ledger, e-invoice, bank) routes through the role agents, is
 * checked by an independent verifier — nothing grades its own homework — and
 * lands on the decision marker. Routes draw in that order on a 9 s cycle.
 *
 * Every element is visible by default (faint base routes), so a failed or
 * reduced-motion render still shows the full map. The loop pauses when the
 * panel is offscreen or the tab is hidden (`data-paused`, see globals.css).
 */

type NodeKind = "source" | "agent" | "verifier" | "decision";
interface AtlasNode { id: string; x: number; y: number; kind: NodeKind }

const NODES: AtlasNode[] = [
  { id: "ledger", x: 46, y: 64, kind: "source" },
  { id: "invoices", x: 46, y: 150, kind: "source" },
  { id: "bank", x: 46, y: 236, kind: "source" },
  { id: "cfo", x: 196, y: 82, kind: "agent" },
  { id: "risk", x: 196, y: 150, kind: "agent" },
  { id: "ceo", x: 196, y: 218, kind: "agent" },
  { id: "verifier", x: 306, y: 150, kind: "verifier" },
  { id: "decision", x: 384, y: 150, kind: "decision" },
];

// [from, to, phase] — phase orders the draw: sources → agents → verifier → decision.
const ROUTES: Array<[string, string, 0 | 1 | 2]> = [
  ["ledger", "cfo", 0],
  ["invoices", "cfo", 0],
  ["invoices", "risk", 0],
  ["bank", "risk", 0],
  ["bank", "ceo", 0],
  ["cfo", "verifier", 1],
  ["risk", "verifier", 1],
  ["ceo", "verifier", 1],
  ["verifier", "decision", 2],
];

const byId = Object.fromEntries(NODES.map((n) => [n.id, n]));

/** Label baseline: sources above their dot, agents/verifier below, decision under its compass. */
function labelY(n: AtlasNode): number {
  if (n.kind === "decision") return n.y + 38;
  if (n.kind === "source") return n.y - 11;
  return n.y + 24;
}

function curve(a: AtlasNode, b: AtlasNode): string {
  const mx = (a.x + b.x) / 2;
  return `M ${a.x} ${a.y} C ${mx} ${a.y}, ${mx} ${b.y}, ${b.x} ${b.y}`;
}

// Hand-drawn terrain behind the routes — contour lines, not a decorative grid.
const CONTOURS = [
  "M -10 270 C 70 236, 120 290, 210 262 S 360 214, 430 248",
  "M -10 290 C 90 262, 150 306, 240 284 S 370 246, 430 270",
  "M -10 34 C 60 58, 140 14, 230 40 S 360 74, 430 30",
  "M 250 -10 C 236 40, 284 70, 268 120 S 236 190, 262 240",
];

export function DecisionAtlas() {
  const { t } = useI18n();
  const a = t.authAtlas;
  const rootRef = useRef<HTMLDivElement>(null);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    let onScreen = true;
    const sync = () => setPaused(!onScreen || document.visibilityState === "hidden");
    const io = new IntersectionObserver(([entry]) => {
      onScreen = entry?.isIntersecting ?? true;
      sync();
    });
    io.observe(el);
    document.addEventListener("visibilitychange", sync);
    return () => {
      io.disconnect();
      document.removeEventListener("visibilitychange", sync);
    };
  }, []);

  const label = (id: string) => a[id as keyof typeof a];

  return (
    <figure ref={rootRef} className="decision-atlas" data-paused={paused ? "true" : undefined}>
      <svg viewBox="0 0 420 300" role="img" aria-label={a.ariaLabel} className="h-auto w-full">
        <g className="atlas-terrain" fill="none">
          {CONTOURS.map((d) => <path key={d} d={d} />)}
        </g>

        {ROUTES.map(([from, to, phase]) => {
          const d = curve(byId[from], byId[to]);
          return (
            <g key={`${from}-${to}`} fill="none" data-phase={phase}>
              <path d={d} className="atlas-route-base" />
              <path d={d} pathLength={1} className="atlas-route-lit" />
              {phase === 0 && <path d={d} pathLength={1} className="atlas-packet" />}
            </g>
          );
        })}

        {NODES.map((n) => {
          const above = n.kind === "source";
          return (
            <g key={n.id} className={`atlas-node atlas-node--${n.kind}`} data-phase={n.kind}>
              {n.kind === "decision" ? (
                <>
                  <circle cx={n.x} cy={n.y} r={22} className="atlas-compass" />
                  <circle cx={n.x} cy={n.y} r={15} className="atlas-halo" />
                  <path
                    d={`M ${n.x} ${n.y - 9} L ${n.x + 9} ${n.y} L ${n.x} ${n.y + 9} L ${n.x - 9} ${n.y} Z`}
                    className="atlas-marker"
                  />
                </>
              ) : (
                <>
                  <circle cx={n.x} cy={n.y} r={n.kind === "source" ? 4 : 6} className="atlas-dot" />
                  {n.kind !== "source" && <circle cx={n.x} cy={n.y} r={11} className="atlas-ring" />}
                </>
              )}
              <text
                x={above ? n.x - 6 : n.x}
                y={labelY(n)}
                textAnchor={above ? "start" : "middle"}
                className="atlas-label"
              >
                {label(n.id)}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="mt-3 text-xs text-parchment-500">{a.caption}</figcaption>
    </figure>
  );
}
