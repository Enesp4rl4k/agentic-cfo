"use client";

import { useEffect, useState, createContext, useContext } from "react";
import { Sun, Moon, Monitor } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

type Theme = "light" | "dark" | "system";

interface ThemeContextValue {
  theme:       Theme;
  setTheme:    (t: Theme) => void;
  resolvedTheme: "light" | "dark";
}

const ThemeContext = createContext<ThemeContextValue>({
  theme:         "system",
  setTheme:      () => {},
  resolvedTheme: "dark",
});

const STORAGE_KEY = "clevelai_theme";

// ── Provider ──────────────────────────────────────────────────────────────────

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme,         setThemeState] = useState<Theme>("system");
  const [resolvedTheme, setResolved]   = useState<"light" | "dark">("dark");

  useEffect(() => {
    // Load saved preference
    const saved = (localStorage.getItem(STORAGE_KEY) as Theme) || "system";
    setThemeState(saved);
    applyTheme(saved);
  }, []);

  function applyTheme(t: Theme) {
    const root = document.documentElement;
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const isDark = t === "dark" || (t === "system" && prefersDark);

    root.classList.toggle("dark", isDark);
    setResolved(isDark ? "dark" : "light");
  }

  function setTheme(t: Theme) {
    setThemeState(t);
    localStorage.setItem(STORAGE_KEY, t);
    applyTheme(t);
  }

  // Listen for system preference changes
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      if (theme === "system") applyTheme("system");
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, setTheme, resolvedTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}

// ── Toggle button (3-way: light / dark / system) ──────────────────────────────

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);
  if (!mounted) return <div className="h-8 w-8" />;

  const options: { value: Theme; icon: React.ReactNode; label: string }[] = [
    { value: "light",  icon: <Sun className="h-3.5 w-3.5" />,     label: "Açık tema" },
    { value: "dark",   icon: <Moon className="h-3.5 w-3.5" />,    label: "Koyu tema" },
    { value: "system", icon: <Monitor className="h-3.5 w-3.5" />, label: "Sistem teması" },
  ];

  return (
    <div
      role="group"
      aria-label="Tema seç"
      className={cn(
        "flex items-center gap-0.5 rounded-lg border border-border bg-muted p-0.5",
        className
      )}
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => setTheme(opt.value)}
          aria-label={opt.label}
          aria-pressed={theme === opt.value}
          className={cn(
            "rounded-md p-1.5 transition-colors",
            theme === opt.value
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          {opt.icon}
        </button>
      ))}
    </div>
  );
}

// ── Simple icon toggle (for compact spaces) ───────────────────────────────────

export function ThemeIconToggle({ className }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);
  if (!mounted) return <div className="h-8 w-8" />;

  return (
    <button
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
      aria-label={resolvedTheme === "dark" ? "Açık temaya geç" : "Koyu temaya geç"}
      className={cn(
        "rounded-md p-1.5 text-muted-foreground transition-colors hover:text-foreground hover:bg-muted",
        className
      )}
    >
      {resolvedTheme === "dark"
        ? <Sun className="h-4 w-4" />
        : <Moon className="h-4 w-4" />
      }
    </button>
  );
}
