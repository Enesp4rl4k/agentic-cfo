/** @type {import('tailwindcss').Config} */
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
        border:      "var(--border)",
        input:       "var(--input)",
        ring:        "var(--ring)",
        background:  "var(--background)",
        foreground:  "var(--foreground)",
        primary: {
          DEFAULT:    "var(--primary)",
          foreground: "var(--primary-foreground)",
        },
        secondary: {
          DEFAULT:    "var(--secondary)",
          foreground: "var(--secondary-foreground)",
        },
        muted: {
          DEFAULT:    "var(--muted)",
          foreground: "var(--muted-foreground)",
        },
        accent: {
          DEFAULT:    "var(--muted)",
          foreground: "var(--muted-foreground)",
        },
        destructive: {
          DEFAULT:    "var(--destructive)",
          foreground: "var(--destructive-foreground)",
        },
        card: {
          DEFAULT:    "var(--card)",
          foreground: "var(--card-foreground)",
        },
        success: {
          DEFAULT:    "var(--success)",
          foreground: "var(--success-foreground)",
        },
        warning: {
          DEFAULT:    "var(--warning)",
          foreground: "var(--warning-foreground)",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
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
  plugins: [require("tailwindcss-animate")],
};
