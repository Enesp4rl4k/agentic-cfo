"use client";

import { useRef, useState, type KeyboardEvent } from "react";
import {
  approvalAmount, curvePoint, curvePoints, formatThousands, formatTry, sampleClose, sampleTotals,
  tabOrder, week6Payments, type BrandLandingMessages, type TabId,
} from "./content";
import { SailMark } from "./SailMark";
import styles from "./brand.module.css";

/**
 * Four-tab product tour. Follows the WAI-ARIA tabs pattern: roving tabindex,
 * Arrow/Home/End move focus *and* selection, each tab names the one panel it
 * controls, the panel is labelled by the active tab. All text comes from the
 * i18n messages passed in as `copy`.
 */

type PanelProps = { copy: BrandLandingMessages["panels"] };

const LOW = formatTry(Math.min(...sampleClose));

function AnswerPanel({ copy }: PanelProps) {
  const a = copy.answer;
  const tiles: readonly (readonly [string, string, boolean])[] = [
    [a.today, formatTry(sampleClose[0]), false],
    [a.collections, formatTry(sampleTotals.collections), false],
    [a.payments, formatTry(sampleTotals.payments), false],
    [a.lowest, LOW, true],
  ];
  return (
    <div className={styles.panelBody}>
      <span className={styles.eyebrow}>{a.date}</span>
      <p className={styles.answer}>
        {a.before}
        <em>{a.em}</em>
        {a.after}
        {formatTry(Math.abs(sampleClose[6]))}
        {a.suffix}
      </p>
      <div className={styles.tiles}>
        {tiles.map(([label, value, bad]) => (
          <div key={label} className={bad ? styles.tileBad : styles.tile}>
            <span>{label}</span>
            <b className={styles.mono}>{value}</b>
          </div>
        ))}
      </div>
      <div className={styles.pills}>
        <span className={styles.pillWarn}>{a.pending}</span>
        <span className={styles.pillOk}>{a.read}</span>
      </div>
    </div>
  );
}

function RoutePanel({ copy }: PanelProps) {
  const r = copy.route;
  const low = curvePoint(6, sampleClose[6]);
  const rows: readonly (readonly [string, number])[] = [
    [r.salaries, week6Payments.salaries],
    [r.suppliers, week6Payments.suppliers],
    [r.fixed, week6Payments.fixed],
  ];
  return (
    <div className={styles.panelBody}>
      <span className={styles.eyebrow}>{r.eyebrow}</span>
      <svg viewBox="-40 -6 1060 316" className={styles.curve} role="img" aria-label={`${r.aria} ${LOW}`}>
        <rect x="0" y="221" width="1000" height="66" fill="#9E1F2E" opacity=".07" />
        <line x1="0" y1="221" x2="1000" y2="221" stroke="var(--ink)" strokeWidth="1.5" />
        <polyline points={curvePoints} fill="none" stroke="var(--ink)" strokeWidth="3.5" strokeLinejoin="round" className={styles.draw} pathLength={1} />
        <circle cx={low.x} cy={low.y} r="10" fill="#C2561C" className={styles.pop} />
      </svg>
      <div className={styles.breakdown}>
        <b>{r.title}</b>
        {rows.map(([label, value]) => (
          <span key={label}>
            <span>{label}</span>
            <span className={styles.mono}>{formatThousands(value)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function ApprovalPanel({ copy }: PanelProps) {
  const p = copy.approval;
  const amount = formatTry(approvalAmount);
  return (
    <div className={styles.panelBody}>
      <span className={styles.eyebrow}>{p.eyebrow}</span>
      <p className={styles.approvalTitle}>
        <b>{`${p.title} ${amount}`}</b>
        {p.rest}
      </p>
      <p className={styles.muted}>{p.note}</p>
      <div className={styles.candidates}>
        <div className={styles.candidateOn}>
          <span><b>{p.a}</b>{p.aDue}</span>
          <span className={styles.mono}>{amount}</span>
        </div>
        <div className={styles.candidate}>
          <span><b>{p.b}</b>{p.bDue}</span>
          <span className={styles.mono}>{amount}</span>
        </div>
      </div>
    </div>
  );
}

function ReportPanel({ copy }: PanelProps) {
  const r = copy.report;
  return (
    <div className={`${styles.panelBody} ${styles.reportRow}`}>
      <div className={styles.paper}>
        <span className={styles.paperHead}><SailMark size={14} small /> {r.paper}</span>
        <svg viewBox="0 0 1000 300" aria-hidden="true"><polyline points={curvePoints} fill="none" stroke="var(--ink)" strokeWidth="10" /></svg>
        <span className={styles.stamp} aria-hidden="true"><SailMark size={34} small ember="#A3440F" /></span>
      </div>
      <div className={styles.archive}>
        <span className={styles.eyebrow}>{r.archive}</span>
        {[r.r1, r.r2, r.r3].map((name) => (
          <span key={name}><span>{name}</span><b>{r.file}</b></span>
        ))}
      </div>
    </div>
  );
}

const PANELS: Record<TabId, (props: PanelProps) => JSX.Element> = {
  cevap: AnswerPanel,
  rota: RoutePanel,
  onay: ApprovalPanel,
  rapor: ReportPanel,
};

export function ProductTabs({ copy }: { copy: BrandLandingMessages }) {
  const [active, setActive] = useState<TabId>("cevap");
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const index = tabOrder.indexOf(active);
  const text = copy.tabs[active];
  const Panel = PANELS[active];

  const select = (i: number) => {
    const next = (i + tabOrder.length) % tabOrder.length;
    setActive(tabOrder[next]);
    refs.current[next]?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    switch (e.key) {
      case "ArrowRight": e.preventDefault(); select(index + 1); break;
      case "ArrowLeft": e.preventDefault(); select(index - 1); break;
      case "Home": e.preventDefault(); select(0); break;
      case "End": e.preventDefault(); select(tabOrder.length - 1); break;
      default: break;
    }
  };

  return (
    <>
      <div className={styles.tablist} role="tablist" aria-label={copy.product.tablistLabel} onKeyDown={onKeyDown}>
        {tabOrder.map((id, i) => (
          <button
            key={id}
            ref={(node) => {
              refs.current[i] = node;
            }}
            id={`tab-${id}`}
            type="button"
            role="tab"
            className={styles.tab}
            aria-selected={id === active}
            aria-controls="urun-panel"
            tabIndex={id === active ? 0 : -1}
            onClick={() => setActive(id)}
          >
            <span className={styles.tabNum}>{String(i + 1).padStart(2, "0")}</span>
            {copy.tabs[id].label}
          </button>
        ))}
      </div>

      <div className={styles.tourRow}>
        <div className={styles.tourText} key={active}>
          <h3 className={styles.display}>{text.title}</h3>
          <p>{text.body}</p>
          <ul>
            {text.bullets.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </div>
        <div className={styles.window} role="tabpanel" id="urun-panel" aria-labelledby={`tab-${active}`}>
          <div className={styles.windowBar}>
            <span /><span /><span />
            <code>{text.path}</code>
          </div>
          <div className={styles.windowBody}>
            <div className={styles.windowRail} aria-hidden="true"><SailMark size={26} small ember="#D9652A" /></div>
            <div className={styles.windowMain} key={active}>
              <Panel copy={copy.panels} />
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
