/**
 * Geometry of the cash curve, kept pure so it can be tested without a browser.
 * Values are the weekly closing amounts (or accumulated movement) in cents.
 * The domain always includes zero: the line a company must not cross is the
 * reason the chart exists.
 */
export const CURVE_WIDTH = 1000;
export const CURVE_HEIGHT = 290;
const PAD_TOP = 16;
const PAD_BOTTOM = 18;

export type CurvePoint = { x: number; y: number; value: number };

export interface CurveGeometry {
  points: CurvePoint[];
  zeroY: number;
  /** Index of the lowest closing value. */
  lowIndex: number;
  ticks: { value: number; y: number }[];
  /** Height of the part below zero, 0 when the curve never goes under it. */
  negativeHeight: number;
}

/** A 1-2-5 step that yields roughly `target` ticks across `range`. */
export function niceStep(range: number, target = 3): number {
  if (!(range > 0)) return 1;
  const raw = range / target;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const unit = raw / pow;
  const mult = unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 5 ? 5 : 10;
  return mult * pow;
}

export function buildCurve(values: number[]): CurveGeometry {
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const step = niceStep(hi - lo);
  const top = Math.ceil(hi / step) * step;
  const bottomValue = Math.floor(lo / step) * step;
  const span = top - bottomValue || step;
  const plotH = CURVE_HEIGHT - PAD_TOP - PAD_BOTTOM;
  const yOf = (v: number) => PAD_TOP + ((top - v) / span) * plotH;

  const n = values.length;
  const points = values.map((value, i) => ({
    x: n <= 1 ? CURVE_WIDTH / 2 : (i / (n - 1)) * CURVE_WIDTH,
    y: yOf(value),
    value,
  }));

  let lowIndex = 0;
  values.forEach((v, i) => {
    if (v < values[lowIndex]) lowIndex = i;
  });

  const ticks: { value: number; y: number }[] = [];
  for (let v = bottomValue; v <= top + step / 2; v += step) {
    ticks.push({ value: Math.abs(v) < step / 1000 ? 0 : v, y: yOf(v) });
  }

  const zeroY = yOf(0);
  return { points, zeroY, lowIndex, ticks, negativeHeight: Math.max(0, yOf(bottomValue) - zeroY) };
}

/** Polyline `points` attribute for the geometry. */
export function polyline(points: CurvePoint[]): string {
  return points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
}
