"use client";

import { useEffect, useRef } from "react";
import { flashLevel, frame, lightningBolt } from "./storm";
import styles from "./brand.module.css";

/**
 * The hero scene: an Aegean ship riding a storm, with Athena small on a distant rock.
 *
 * The first paint (and the reduced-motion paint) is one deterministic frame, so
 * server and client markup agree. Afterwards a single requestAnimationFrame loop
 * writes attributes straight into the SVG; React never re-renders it. The loop
 * stops when the scene is offscreen or the tab is hidden, and never starts under
 * `prefers-reduced-motion`.
 */

const INITIAL = frame(2);
const PARTICLES = 40;

type Particle = { x: number; y: number; vx: number; vy: number; life: number };

export function StormShip({ label }: { label: string }) {
  const el = useRef<Record<string, SVGElement | null>>({});
  const drops = useRef<(SVGCircleElement | null)[]>([]);
  const ref = (key: string) => (node: SVGElement | null) => {
    el.current[key] = node;
  };

  useEffect(() => {
    const reduce =
      typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || typeof requestAnimationFrame !== "function") return;

    const root = el.current.root;
    const set = (key: string, attr: string, value: string) => el.current[key]?.setAttribute(attr, value);

    const particles: Particle[] = Array.from({ length: PARTICLES }, () => ({ x: -20, y: -20, vx: 0, vy: 0, life: 0 }));
    let raf = 0;
    let visible = true;
    let bolt = "0,0 0,0";
    let flashAt = -1;
    let nextFlash = 3 + Math.random() * 3;
    let prevBow: number | null = null;
    const t0 = performance.now();
    let last = t0;

    const step = (now: number) => {
      if (!visible) {
        raf = 0;
        return;
      }
      const t = 2 + (now - t0) / 1000;
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;

      if (flashAt < 0 && t > nextFlash) {
        flashAt = t;
        bolt = lightningBolt();
      }
      let flash = 0;
      if (flashAt >= 0) {
        const u = t - flashAt;
        flash = flashLevel(u);
        if (u > 0.8) {
          flashAt = -1;
          nextFlash = t + 4 + Math.random() * 7;
        }
      }

      const f = frame(t);
      set("w1", "d", f.w1); set("w2", "d", f.w2); set("w2c", "d", f.w2c);
      set("w3", "d", f.w3); set("w3c", "d", f.w3c);
      set("sail", "d", f.sail); set("sailS", "d", f.sail);
      set("b0", "d", f.b0); set("b1", "d", f.b1); set("b2", "d", f.b2); set("b3", "d", f.b3);
      set("pen", "d", f.pen); set("sh1", "d", f.sh1); set("sh2", "d", f.sh2);
      set("ship", "transform", f.ship);
      set("c1", "transform", f.c1); set("c2", "transform", f.c2); set("c3", "transform", f.c3);
      set("rain", "patternTransform", f.rain); set("rain2", "patternTransform", f.rain2);
      set("flash", "opacity", (flash * 0.32).toFixed(3));
      set("bolt", "points", bolt);
      set("bolt", "opacity", flash > 0.1 ? flash.toFixed(2) : "0");

      // Bow spray: drops leave the bow when the ship plunges into a wave.
      const a = f.shipAngle / 57.2958;
      const bowX = f.shipX + 0.9 * 110 * Math.cos(a);
      const bowY = f.shipY + 0.9 * (110 * Math.sin(a) + 6);
      if (prevBow !== null && bowY - prevBow > 0.35) {
        const burst = Math.min(3, Math.floor((bowY - prevBow) * 3));
        let spawned = 0;
        for (const p of particles) {
          if (spawned >= burst) break;
          if (p.life <= 0) {
            p.x = bowX + Math.random() * 10;
            p.y = bowY - 2;
            p.vx = 30 + Math.random() * 70;
            p.vy = -70 - Math.random() * 90;
            p.life = 0.7 + Math.random() * 0.5;
            spawned++;
          }
        }
      }
      prevBow = bowY;
      particles.forEach((p, i) => {
        if (p.life > 0) {
          p.vy += 260 * dt;
          p.x += p.vx * dt;
          p.y += p.vy * dt;
          p.life -= dt;
        }
        const c = drops.current[i];
        if (c) {
          c.setAttribute("cx", p.x.toFixed(1));
          c.setAttribute("cy", p.y.toFixed(1));
          c.setAttribute("opacity", p.life > 0 ? Math.min(0.85, p.life).toFixed(2) : "0");
        }
      });

      raf = requestAnimationFrame(step);
    };

    raf = requestAnimationFrame(step);

    const observer =
      typeof IntersectionObserver === "function" && root
        ? new IntersectionObserver(([entry]) => {
            visible = entry.isIntersecting;
            if (visible && raf === 0) {
              last = performance.now();
              raf = requestAnimationFrame(step);
            }
          })
        : null;
    if (root && observer) observer.observe(root);

    return () => {
      cancelAnimationFrame(raf);
      observer?.disconnect();
    };
  }, []);

  return (
    <svg
      ref={ref("root")}
      className={styles.stormSvg}
      viewBox="0 0 800 500"
      preserveAspectRatio="xMidYMid slice"
      role="img"
      aria-label={label}
    >
      <defs>
        <linearGradient id="tcsSky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#121216" /><stop offset=".55" stopColor="#23232A" /><stop offset="1" stopColor="#2C2C33" />
        </linearGradient>
        <radialGradient id="tcsGlow" cx="70%" cy="32%" r="55%">
          <stop offset="0" stopColor="#3A3530" stopOpacity=".9" /><stop offset="1" stopColor="#3A3530" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="tcsSail" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#8E3A0E" /><stop offset=".3" stopColor="#C2561C" /><stop offset=".55" stopColor="#E0733A" /><stop offset=".8" stopColor="#C2561C" /><stop offset="1" stopColor="#8E3A0E" />
        </linearGradient>
        <linearGradient id="tcsSailShade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#000" stopOpacity=".18" /><stop offset=".35" stopColor="#000" stopOpacity="0" /><stop offset="1" stopColor="#000" stopOpacity=".22" />
        </linearGradient>
        <linearGradient id="tcsHull" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#F2EBDD" /><stop offset=".6" stopColor="#D9CDB4" /><stop offset="1" stopColor="#A89C84" />
        </linearGradient>
        <linearGradient id="tcsW3" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#24242B" /><stop offset="1" stopColor="#121216" />
        </linearGradient>
        <filter id="tcsBlur" x="-30%" y="-60%" width="160%" height="220%"><feGaussianBlur stdDeviation="16" /></filter>
        <pattern ref={ref("rain")} id="tcsRain" width="16" height="22" patternUnits="userSpaceOnUse" patternTransform={INITIAL.rain}>
          <line x1="0" y1="0" x2="0" y2="11" stroke="#A9A396" strokeWidth="1" opacity=".38" />
        </pattern>
        <pattern ref={ref("rain2")} id="tcsRain2" width="27" height="31" patternUnits="userSpaceOnUse" patternTransform={INITIAL.rain2}>
          <line x1="3" y1="0" x2="3" y2="16" stroke="#CFC3AA" strokeWidth="1.2" opacity=".22" />
        </pattern>
      </defs>

      <rect width="800" height="500" fill="url(#tcsSky)" />
      <rect width="800" height="500" fill="url(#tcsGlow)" />
      <g filter="url(#tcsBlur)" fill="#0E0E12" opacity=".85">
        <ellipse ref={ref("c1")} cx="180" cy="70" rx="220" ry="46" transform={INITIAL.c1} />
        <ellipse ref={ref("c2")} cx="560" cy="44" rx="260" ry="40" transform={INITIAL.c2} />
        <ellipse ref={ref("c3")} cx="380" cy="128" rx="200" ry="30" transform={INITIAL.c3} opacity=".6" />
      </g>
      <polyline ref={ref("bolt")} points="0,0 0,0" fill="none" stroke="#F6E7CF" strokeWidth="2.4" strokeLinejoin="bevel" opacity="0" />

      {/* Distant rock and a small Athena: one-colour silhouette, no detail at this distance. */}
      <path d="M612 302 L630 284 L668 276 L706 282 L732 296 L748 306 Z" fill="#1E1E24" />
      <g transform="translate(664 222) scale(.16)" fill="#34343C">
        <rect x="40" y="370" width="120" height="14" /><rect x="30" y="384" width="140" height="12" />
        <path d="M80 118 C76 160 70 250 64 370 L136 370 C130 250 124 160 120 118 Z" />
        <rect x="94" y="90" width="12" height="22" /><circle cx="100" cy="80" r="15" />
        <path d="M84 64 C88 30 122 26 132 56 C122 46 106 44 98 62 Z" fill="#6A3519" />
        <line x1="150" y1="30" x2="150" y2="372" stroke="#34343C" strokeWidth="3.5" />
        <circle cx="54" cy="300" r="42" />
      </g>

      <path ref={ref("w1")} d={INITIAL.w1} fill="#26262D" />
      <path ref={ref("w2")} d={INITIAL.w2} fill="#2D2D35" />
      <path ref={ref("w2c")} d={INITIAL.w2c} fill="none" stroke="#F2EBDD" strokeWidth="1.2" opacity=".18" />

      <g ref={ref("ship")} transform={INITIAL.ship}>
        <line x1="-90" y1="-4" x2="-114" y2="44" stroke="#CFC3AA" strokeWidth="4.5" strokeLinecap="round" />
        <line x1="0" y1="-158" x2="114" y2="-40" stroke="#CFC3AA" strokeWidth="1" opacity=".75" />
        <line x1="0" y1="-158" x2="-104" y2="-62" stroke="#CFC3AA" strokeWidth="1" opacity=".75" />
        <line x1="0" y1="8" x2="0" y2="-160" stroke="#E8DFCC" strokeWidth="4.2" strokeLinecap="round" />
        <path ref={ref("pen")} d={INITIAL.pen} fill="#C2561C" />
        <path ref={ref("sail")} d={INITIAL.sail} fill="url(#tcsSail)" />
        <path ref={ref("sailS")} d={INITIAL.sail} fill="url(#tcsSailShade)" />
        <g stroke="#5A2508" strokeWidth="1.1" fill="none" opacity=".55">
          <path ref={ref("b0")} d={INITIAL.b0} /><path ref={ref("b1")} d={INITIAL.b1} />
          <path ref={ref("b2")} d={INITIAL.b2} /><path ref={ref("b3")} d={INITIAL.b3} />
        </g>
        <path d="M-64 -131 Q0 -137 64 -131" fill="none" stroke="#E8DFCC" strokeWidth="3.6" strokeLinecap="round" />
        <path ref={ref("sh1")} d={INITIAL.sh1} fill="none" stroke="#CFC3AA" strokeWidth="1" opacity=".8" />
        <path ref={ref("sh2")} d={INITIAL.sh2} fill="none" stroke="#CFC3AA" strokeWidth="1" opacity=".8" />
        <path d="M-104 -10 C-124 -26 -120 -60 -102 -64 C-92 -66 -86 -56 -94 -50" fill="none" stroke="#E8DFCC" strokeWidth="6" strokeLinecap="round" />
        <path d="M-104 -10 C-60 12 60 12 100 -14 L112 -40 C114 -46 121 -45 119 -39 L110 -8 C94 24 40 32 -10 30 C-58 28 -92 16 -104 -10 Z" fill="url(#tcsHull)" />
        <path d="M-96 0 C-50 18 50 18 104 -4" fill="none" stroke="#8C8068" strokeWidth="1.2" opacity=".7" />
        <path d="M-86 10 C-40 26 40 26 98 8" fill="none" stroke="#8C8068" strokeWidth="1.2" opacity=".6" />
        <path d="M-104 -10 C-60 12 60 12 100 -14" fill="none" stroke="#6E6450" strokeWidth="2" />
        <circle cx="98" cy="-6" r="5" fill="#F2EBDD" stroke="#1A1A1F" strokeWidth="1.4" />
        <circle cx="98.6" cy="-6" r="2.6" fill="#C2561C" />
      </g>

      <g fill="#F2EBDD">
        {Array.from({ length: PARTICLES }, (_, i) => (
          <circle
            key={i}
            ref={(node) => {
              drops.current[i] = node;
            }}
            cx="-20"
            cy="-20"
            r={(1.1 + (i % 4) * 0.45).toFixed(2)}
            opacity="0"
          />
        ))}
      </g>

      <path ref={ref("w3")} d={INITIAL.w3} fill="url(#tcsW3)" />
      <path ref={ref("w3c")} d={INITIAL.w3c} fill="none" stroke="#F2EBDD" strokeWidth="1.6" opacity=".3" />

      <rect width="800" height="500" fill="url(#tcsRain)" transform="rotate(14 400 250) scale(1.2)" pointerEvents="none" />
      <rect width="800" height="500" fill="url(#tcsRain2)" transform="rotate(14 400 250) scale(1.2)" pointerEvents="none" />
      <rect ref={ref("flash")} width="800" height="500" fill="#F2EBDD" opacity="0" pointerEvents="none" />
    </svg>
  );
}
