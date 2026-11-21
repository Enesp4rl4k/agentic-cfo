"use client";

import { useI18n } from "@/hooks/useI18n";
import type { RadarWeek } from "@/lib/api/ledger";
import { cn } from "@/lib/utils";
import { buildCurve, CURVE_HEIGHT, CURVE_WIDTH, polyline } from "./curve";

type Copy = ReturnType<typeof useI18n>["t"]["cashRadar"];

/**
 * The cash curve of the route: one closing value per week, the zero line, the
 * part below it tinted, the lowest week marked, the chosen week banded. The svg
 * is a picture for the eye; the table beside it is the keyboard and screen-reader
 * way to the same weeks, so the dots here are pointer-only.
 */
export function RadarCurve({
  weeks,
  known,
  selected,
  onSelect,
  copy,
  fmt,
  locale,
}: {
  weeks: RadarWeek[];
  known: boolean;
  selected: number | null;
  onSelect: (week: number) => void;
  copy: Copy;
  fmt: (value: number) => string;
  locale: string;
}) {
  const geo = buildCurve(weeks.map((w) => w.end_balance_cents));
  const compact = new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 });
  const low = geo.points[geo.lowIndex];
  const lowWeek = weeks[geo.lowIndex];
  const goesNegative = low !== undefined && low.value < 0;
  const aria = goesNegative
    ? copy.curveAria.replace("{week}", String(lowWeek.week)).replace("{amount}", fmt(low.value / 100))
    : copy.curveAriaFlat;
  const step = weeks.length > 1 ? CURVE_WIDTH / (weeks.length - 1) : CURVE_WIDTH;
  const labelEvery = weeks.length > 9 ? 2 : 1;

  return (
    <figure className="m-0 space-y-3">
      <figcaption className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[13px] text-muted-foreground">
        <span className="inline-flex items-center gap-2">
          <span className="inline-block h-[3px] w-[22px] bg-foreground" aria-hidden="true" />
          {known ? copy.curveUnit : copy.curveMovementUnit}
        </span>
        <span className="ml-auto inline-flex items-center gap-2">
          <span
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ background: "var(--tc-zone)", outline: "1px solid var(--destructive)" }}
            aria-hidden="true"
          />
          {copy.curveZero}
        </span>
      </figcaption>
      <svg
        viewBox={`-76 0 ${CURVE_WIDTH + 92} ${CURVE_HEIGHT + 26}`}
        className="block h-auto w-full min-w-[520px]"
        role="img"
        aria-label={aria}
      >
        {geo.negativeHeight > 0 && (
          <rect x={0} y={geo.zeroY} width={CURVE_WIDTH} height={geo.negativeHeight} fill="var(--tc-zone)" />
        )}
        <g stroke="var(--border)" strokeWidth={1}>
          {geo.ticks
            .filter((t) => t.value !== 0)
            .map((t) => (
              <line key={t.value} x1={0} y1={t.y} x2={CURVE_WIDTH} y2={t.y} />
            ))}
        </g>
        <line x1={0} y1={geo.zeroY} x2={CURVE_WIDTH} y2={geo.zeroY} stroke="var(--foreground)" strokeWidth={1.5} />
        <g className="tc-mono" fontSize={14} fill="var(--muted-foreground)" textAnchor="end">
          {geo.ticks.map((t) => (
            <text key={t.value} x={-8} y={t.y + 5}>
              {compact.format(t.value / 100).replace("-", "−")}
            </text>
          ))}
        </g>
        {weeks.map((w, i) =>
          w.week === selected ? (
            <rect
              key={w.week}
              x={geo.points[i].x - step / 2}
              y={0}
              width={step}
              height={CURVE_HEIGHT - 8}
              fill="var(--tc-ember)"
              opacity={0.1}
            />
          ) : null,
        )}
        <polyline
          points={polyline(geo.points)}
          fill="none"
          stroke="var(--foreground)"
          strokeWidth={3}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {geo.points.map((p, i) => {
          const week = weeks[i];
          const isLow = goesNegative && i === geo.lowIndex;
          const isSelected = week.week === selected;
          return (
            <g key={week.week} onClick={() => onSelect(week.week)} className="cursor-pointer">
              <circle cx={p.x} cy={p.y} r={18} fill="transparent" />
              <circle
                cx={p.x}
                cy={p.y}
                r={isLow || isSelected ? 8 : 4.5}
                fill={isSelected ? "var(--tc-ember)" : isLow ? "var(--foreground)" : "var(--background)"}
                stroke="var(--foreground)"
                strokeWidth={isLow || isSelected ? 0 : 2}
              />
            </g>
          );
        })}
        <g className="tc-mono" fontSize={13} fill="var(--muted-foreground)" textAnchor="middle">
          {geo.points.map((p, i) =>
            i % labelEvery === 0 ? (
              <text key={weeks[i].week} x={p.x} y={CURVE_HEIGHT + 18} className={cn(weeks[i].week === selected && "font-semibold")}>
                {weeks[i].week}
              </text>
            ) : null,
          )}
        </g>
      </svg>
    </figure>
  );
}
