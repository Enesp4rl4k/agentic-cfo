/** @type {import('tailwindcss').Config} */
const colors = require("tailwindcss/colors");
const plugin = require("tailwindcss/plugin");

/**
 * Tunç Çağı colour plumbing (DESIGN.md).
 *
 * 1. Semantic tokens (`bg-primary`, `border-border`…) point at CSS variables that hold whole
 *    colours. Tailwind 3 cannot put an opacity on such a value, so `bg-primary/5` produced no
 *    CSS at all. `alpha()` builds the colour with color-mix when an opacity is asked for.
 * 2. Status hues written straight into pages (`text-emerald-400`, `bg-red-950`…) were chosen for
 *    a dark-only app. Each hue is a variable scale: dark mode keeps Tailwind's own values, light
 *    mode swaps the pale text steps and the dark tints with their opposites (400 reads as 800,
 *    950 as 50) and darkens the middle steps one notch, so the same class stays legible on cream
 *    without touching the ~1500 places that use them.
 */
const alpha = (name) => ({ opacityValue }) =>
  opacityValue === undefined
    ? `var(${name})`
    : `color-mix(in srgb, var(${name}) calc(${opacityValue} * 100%), transparent)`;

const STEPS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
const HUES = ["emerald", "red", "amber", "orange", "yellow", "blue", "stone"];

const channels = (hex) => {
  const n = parseInt(hex.slice(1), 16);
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`;
};
const hueScale = (hue) =>
  Object.fromEntries(STEPS.map((step) => [step, `rgb(var(--c-${hue}-${step}) / <alpha-value>)`]));
// Light mode: the pale steps that carry text on ink (50-400) and the dark tinted surfaces
// (800-950) swap sides, and the middle steps move one notch darker so text and white-on-colour
// fills keep 4.5:1 on cream.
const LIGHT_SOURCE = { 50: 950, 100: 950, 200: 900, 300: 900, 400: 800, 500: 600, 600: 700, 700: 800, 800: 200, 900: 100, 950: 50 };
const hueVars = (light) =>
  Object.fromEntries(
    HUES.flatMap((hue) =>
      STEPS.map((step) => [`--c-${hue}-${step}`, channels(colors[hue][light ? LIGHT_SOURCE[step] : step])]),
    ),
  );

module.exports = {
  darkMode: ["class"],
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        border:      alpha("--border"),
        input:       alpha("--input"),
        ring:        alpha("--ring"),
        background:  alpha("--background"),
        foreground:  alpha("--foreground"),
        primary: {
          DEFAULT:    alpha("--primary"),
          foreground: alpha("--primary-foreground"),
        },
        secondary: {
          DEFAULT:    alpha("--secondary"),
          foreground: alpha("--secondary-foreground"),
        },
        muted: {
          DEFAULT:    alpha("--muted"),
          foreground: alpha("--muted-foreground"),
        },
        accent: {
          DEFAULT:    alpha("--muted"),
          foreground: alpha("--muted-foreground"),
        },
        destructive: {
          DEFAULT:    alpha("--destructive"),
          foreground: alpha("--destructive-foreground"),
        },
        card: {
          DEFAULT:    alpha("--card"),
          foreground: alpha("--card-foreground"),
        },
        success: {
          DEFAULT:    alpha("--success"),
          foreground: alpha("--success-foreground"),
        },
        warning: {
          DEFAULT:    alpha("--warning"),
          foreground: alpha("--warning-foreground"),
        },

        // Status hues, mirrored in light mode (see the plumbing note above).
        emerald: hueScale("emerald"),
        red: hueScale("red"),
        amber: hueScale("amber"),
        orange: hueScale("orange"),
        yellow: hueScale("yellow"),
        blue: hueScale("blue"),

        // The old Karar Atlası accents, kept as names so no page breaks, now drawn from the
        // brand's scales: brass and copper are ember (orange), clay is red, sage is green,
        // mapblue is blue, parchment is the warm neutral.
        brass: hueScale("orange"),
        copper: hueScale("orange"),
        clay: hueScale("red"),
        sage: hueScale("emerald"),
        mapblue: hueScale("blue"),
        parchment: hueScale("stone"),
      },
      borderRadius: {
        lg: alpha("--radius"),
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["var(--tc-font-body)", "system-ui", "sans-serif"],
        display: ["var(--tc-font-display)", "Georgia", "serif"],
        cinzel: ["var(--tc-font-cinzel)", "serif"],
        mono: ["var(--tc-font-mono)", "ui-monospace", "monospace"],
      },

      // ── Impeccable-style animation timing ──────────────────────────────────
      transitionTimingFunction: {
        "out-quart":  "cubic-bezier(0.25, 1, 0.5, 1)",
        "out-expo":   "cubic-bezier(0.16, 1, 0.3, 1)",
        "out-spring": "cubic-bezier(0.34, 1.56, 0.64, 1)",
        "in-quart":   "cubic-bezier(0.76, 0, 0.24, 1)",
        "spring":     "cubic-bezier(0.34, 1.56, 0.64, 1)",
      },
      transitionDuration: {
        "50":  "50ms",
        "150": "150ms",
        "250": "250ms",
        "350": "350ms",
        "400": "400ms",
        "600": "600ms",
        "800": "800ms",
      },

      // ── Animation keyframes ────────────────────────────────────────────────
      keyframes: {
        // Fade in — opacity only, no layout
        "fade-in": {
          "0%":   { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "fade-out": {
          "0%":   { opacity: "1" },
          "100%": { opacity: "0" },
        },

        // Slide up — for cards/panels entering
        "slide-up": {
          "0%":   { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "slide-down": {
          "0%":   { opacity: "0", transform: "translateY(-8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "slide-left": {
          "0%":   { opacity: "0", transform: "translateX(8px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },

        // Scale in — for modals/popovers
        "scale-in": {
          "0%":   { opacity: "0", transform: "scale(0.95)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
        "scale-out": {
          "0%":   { opacity: "1", transform: "scale(1)" },
          "100%": { opacity: "0", transform: "scale(0.95)" },
        },

        // Shimmer — skeleton loading
        "shimmer": {
          "0%":   { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },

        // Pulse ring — for live indicators
        "ping-slow": {
          "75%, 100%": { transform: "scale(2)", opacity: "0" },
        },

        // Number count up — for KPI cards
        "count-up": {
          "0%":   { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },

        // Progress fill — for bar charts entering
        "fill-width": {
          "0%":   { width: "0%" },
          "100%": { width: "var(--fill-width, 100%)" },
        },

        // Spinner variants
        "spin-slow": {
          "0%":   { transform: "rotate(0deg)" },
          "100%": { transform: "rotate(360deg)" },
        },

        // Toast slide in from right
        "toast-in": {
          "0%":   { opacity: "0", transform: "translateX(100%)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        "toast-out": {
          "0%":   { opacity: "1", transform: "translateX(0)" },
          "100%": { opacity: "0", transform: "translateX(100%)" },
        },

        // Sidebar item stagger reveal
        "stagger-in": {
          "0%":   { opacity: "0", transform: "translateX(-6px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },

        // Card hover lift
        "lift": {
          "0%":   { transform: "translateY(0) scale(1)" },
          "100%": { transform: "translateY(-2px) scale(1.005)" },
        },

        // Gradient drift — for hero/brand surfaces
        "gradient-drift": {
          "0%, 100%": { backgroundPosition: "0% 50%" },
          "50%":       { backgroundPosition: "100% 50%" },
        },

        // Check mark draw — for success states
        "draw-check": {
          "0%":   { strokeDashoffset: "24", opacity: "0" },
          "40%":  { opacity: "1" },
          "100%": { strokeDashoffset: "0", opacity: "1" },
        },

        // Bounce subtle — for notification dot
        "bounce-subtle": {
          "0%, 100%": { transform: "translateY(0)" },
          "50%":       { transform: "translateY(-3px)" },
        },

        // Typewriter cursor blink
        "blink": {
          "0%, 100%": { opacity: "1" },
          "50%":       { opacity: "0" },
        },
      },

      // ── Named animation classes ────────────────────────────────────────────
      animation: {
        // Reveal
        "fade-in":    "fade-in 200ms ease-out-quart both",
        "fade-out":   "fade-out 150ms ease-in-quart both",
        "slide-up":   "slide-up 250ms cubic-bezier(0.25, 1, 0.5, 1) both",
        "slide-down": "slide-down 250ms cubic-bezier(0.25, 1, 0.5, 1) both",
        "slide-left": "slide-left 250ms cubic-bezier(0.25, 1, 0.5, 1) both",
        "scale-in":   "scale-in 200ms cubic-bezier(0.34, 1.56, 0.64, 1) both",
        "scale-out":  "scale-out 150ms ease-in-quart both",

        // Loading
        "shimmer":    "shimmer 1.8s linear infinite",
        "spin-slow":  "spin-slow 2s linear infinite",
        "ping-slow":  "ping-slow 2s cubic-bezier(0, 0, 0.2, 1) infinite",

        // Interactive
        "count-up":   "count-up 300ms cubic-bezier(0.25, 1, 0.5, 1) both",
        "fill-width": "fill-width 600ms cubic-bezier(0.25, 1, 0.5, 1) both",
        "stagger-in": "stagger-in 250ms cubic-bezier(0.25, 1, 0.5, 1) both",

        // Toast
        "toast-in":   "toast-in 300ms cubic-bezier(0.34, 1.56, 0.64, 1) both",
        "toast-out":  "toast-out 200ms ease-in-quart both",

        // Brand
        "gradient-drift": "gradient-drift 6s ease infinite",
        "draw-check":     "draw-check 500ms cubic-bezier(0.25, 1, 0.5, 1) both",
        "bounce-subtle":  "bounce-subtle 1.5s ease-in-out infinite",
        "blink":          "blink 1s step-start infinite",
      },
    },
  },
  plugins: [
    require("tailwindcss-animate"),
    plugin(({ addBase }) => {
      addBase({ ":root": hueVars(true), ".dark": hueVars(false) });
    }),
  ],
};
