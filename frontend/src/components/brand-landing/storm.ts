/**
 * Storm scene maths. Pure functions, no DOM: the component calls `frame(t)` each
 * animation frame and writes the strings into the SVG.
 *
 * Waves are sums of three sine components per layer (amplitude, wavenumber,
 * speed, phase) with a horizontal displacement, which gives the sharp crests and
 * wide troughs of a real sea. The ship reads the middle wave's height and slope
 * under its keel each frame, so it rides the swell instead of bobbing on a loop.
 */

type WaveComponent = readonly [amp: number, k: number, speed: number, phase: number];
type Wave = { readonly base: number; readonly c: readonly WaveComponent[] };

const L1: Wave = { base: 300, c: [[9, 0.013, 0.55, 0], [5, 0.029, -0.8, 1.7]] };
const L2: Wave = { base: 338, c: [[15, 0.0092, 0.85, 0.4], [7, 0.021, -1.15, 2.2], [3.5, 0.052, 1.8, 0.9]] };
const L3: Wave = { base: 410, c: [[19, 0.0078, 1.05, 1.1], [8, 0.019, -1.35, 0.3], [3.5, 0.047, 2.1, 2.6]] };

export const SHIP_X = 360;
const RAD_TO_DEG = 57.2958;

const n = (v: number): string => v.toFixed(1);

function wavePoints(layer: Wave, t: number): string[] {
  const pts: string[] = [];
  for (let p = -60; p <= 860; p += 8) {
    let x = p;
    let y = layer.base;
    for (const [amp, k, speed, phase] of layer.c) {
      const ph = k * p - speed * t + phase;
      x -= 0.65 * amp * Math.cos(ph);
      y -= amp * Math.sin(ph);
    }
    pts.push(`${n(x)} ${n(y)}`);
  }
  return pts;
}

/** Height and slope of a wave layer at x. */
export function waveAt(layer: Wave, x: number, t: number): { y: number; slope: number } {
  let y = layer.base;
  let slope = 0;
  for (const [amp, k, speed, phase] of layer.c) {
    const ph = k * x - speed * t + phase;
    y -= amp * Math.sin(ph);
    slope -= amp * k * Math.cos(ph);
  }
  return { y, slope };
}

export type Frame = {
  w1: string; w2: string; w2c: string; w3: string; w3c: string;
  ship: string; sail: string;
  b0: string; b1: string; b2: string; b3: string;
  pen: string; sh1: string; sh2: string;
  c1: string; c2: string; c3: string;
  rain: string; rain2: string;
  /** Ship position and heading, used for the bow spray. */
  shipX: number; shipY: number; shipAngle: number;
};

export function frame(t: number): Frame {
  const p1 = wavePoints(L1, t);
  const p2 = wavePoints(L2, t);
  const p3 = wavePoints(L3, t);
  const close = " L860 520 L-60 520 Z";

  const under = waveAt(L2, SHIP_X, t);
  const angle = Math.atan(under.slope) * RAD_TO_DEG * 0.9 + 1.6 * Math.sin(t * 1.3);
  const shipY = under.y + 9;

  // Wind: two rhythms, so the sail never settles.
  const b = 0.62 + 0.26 * Math.sin(t * 0.9) + 0.12 * Math.sin(t * 2.3 + 1);
  const foot = (x: number): number => -46 + 17 * b * (1 - (x / 52) * (x / 52)) + 4 * b * (x / 52);

  const sail =
    `M-60 -130 Q${n(-62 - 7 * b)} -88 -52 -46 C-20 ${n(-46 + 15 * b)} 20 ${n(-46 + 21 * b)} 52 -46 ` +
    `Q${n(60 + 11 * b)} -88 60 -130 Q0 ${n(-127 + 2 * b)} -60 -130 Z`;
  const brail = (x: number): string =>
    `M${n(x)} -129 Q${n(x + 6 * b * (x / 30))} -88 ${n(x * 0.94)} ${n(foot(x * 0.94))}`;

  let pen = "M0 -158";
  for (let k = 1; k <= 7; k++) {
    pen += ` L${n(k * 4.5)} ${n(-158 + Math.sin(t * 9 - k * 0.9) * (0.6 + k * 0.45) - k * 0.15)}`;
  }
  for (let k = 7; k >= 0; k--) {
    pen += ` L${n(k * 4.5)} ${n(-152 + Math.sin(t * 9 - k * 0.9) * (0.6 + k * 0.45) - k * 0.55)}`;
  }
  pen += " Z";

  return {
    w1: `M${p1.join(" L")}${close}`,
    w2: `M${p2.join(" L")}${close}`,
    w2c: `M${p2.join(" L")}`,
    w3: `M${p3.join(" L")}${close}`,
    w3c: `M${p3.join(" L")}`,
    ship: `translate(${n(SHIP_X)} ${n(shipY)}) rotate(${n(angle)}) scale(.9)`,
    sail,
    b0: brail(-33), b1: brail(-11), b2: brail(11), b3: brail(33),
    pen,
    sh1: `M-52 -46 Q-64 ${n(-30 + 4 * b)} -72 -12`,
    sh2: `M52 -46 Q66 ${n(-30 + 5 * b)} 78 -16`,
    c1: `translate(${n((t * 7) % 1100 - 200)} 0)`,
    c2: `translate(${n((t * 4.5 + 500) % 1200 - 400)} 0)`,
    c3: `translate(${n((t * 10 + 200) % 1100 - 300)} 0)`,
    rain: `translate(0 ${n((t * 520) % 22)})`,
    rain2: `translate(0 ${n((t * 720) % 31)})`,
    shipX: SHIP_X,
    shipY,
    shipAngle: angle,
  };
}

/** A forked lightning bolt as SVG polyline points. `rand` is injected for tests. */
export function lightningBolt(rand: () => number = Math.random): string {
  let x = 470 + rand() * 280;
  let y = 0;
  const pts = [`${x.toFixed(0)},${y.toFixed(0)}`];
  while (y < 230) {
    x += (rand() - 0.5) * 46;
    y += 22 + rand() * 26;
    pts.push(`${x.toFixed(0)},${y.toFixed(0)}`);
  }
  return pts.join(" ");
}

/** Flash intensity 0..1 `u` seconds after a strike: a double flicker, then a fade. */
export function flashLevel(u: number): number {
  if (u < 0) return 0;
  if (u < 0.07) return 1;
  if (u < 0.14) return 0.15;
  if (u < 0.22) return 0.85;
  if (u < 0.75) return 0.85 * (1 - (u - 0.22) / 0.53);
  return 0;
}
