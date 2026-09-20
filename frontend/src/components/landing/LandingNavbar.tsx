"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Menu, X } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { cn } from "@/lib/utils";
import { brand } from "@/lib/branding";

const NAV_LINKS = [
  { href: "#özellikler",    label: "Özellikler"     },
  { href: "#ajanlar",       label: "Ajanlar"        },
  { href: "#fiyatlandırma", label: "Fiyatlandırma"  },
  { href: "#social-proof",  label: "Hakkında"       },
];

export function LandingNavbar() {
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Detect scroll to apply glass effect
  useEffect(() => {
    function onScroll() {
      setScrolled(window.scrollY > 20);
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Close mobile menu on resize to desktop
  useEffect(() => {
    function onResize() {
      if (window.innerWidth >= 768) setMobileOpen(false);
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // Prevent body scroll when mobile menu is open
  useEffect(() => {
    document.body.style.overflow = mobileOpen ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [mobileOpen]);

  return (
    <>
      <header
        className={cn(
          "fixed top-0 z-50 w-full transition-all duration-300",
          scrolled
            ? "border-b border-white/8 bg-background/90 shadow-sm backdrop-blur-md"
            : "bg-transparent"
        )}
        role="banner"
      >
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">

          {/* Logo */}
          <Link href="/" aria-label={`${brand.name} — Ana Sayfa`}>
            <Logo size="md" />
          </Link>

          {/* Desktop nav */}
          <nav
            className="hidden items-center gap-1 md:flex"
            aria-label="Ana navigasyon"
          >
            {NAV_LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                className="rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-white/6 hover:text-foreground"
              >
                {link.label}
              </a>
            ))}
          </nav>

          {/* Desktop CTAs */}
          <div className="hidden items-center gap-2 md:flex">
            <Link
              href="/auth/login"
              className="rounded-md px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Giriş Yap
            </Link>
            <Link
              href="/auth/register"
              className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 press-feedback focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Ücretsiz Başla
            </Link>
          </div>

          {/* Mobile hamburger */}
          <button
            type="button"
            onClick={() => setMobileOpen((v) => !v)}
            className="inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-white/8 hover:text-foreground md:hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={mobileOpen ? "Menüyü kapat" : "Menüyü aç"}
            aria-expanded={mobileOpen}
            aria-controls="mobile-menu"
          >
            {mobileOpen
              ? <X className="h-5 w-5" aria-hidden="true" />
              : <Menu className="h-5 w-5" aria-hidden="true" />
            }
          </button>
        </div>
      </header>

      {/* ── Mobile menu overlay ────────────────────────────────────────────── */}
      {mobileOpen && (
        <div
          id="mobile-menu"
          role="dialog"
          aria-modal="true"
          aria-label="Mobil navigasyon"
          className="fixed inset-0 z-40 flex flex-col"
          style={{ paddingTop: "4rem" }}
        >
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-background/95 backdrop-blur-md"
            aria-hidden="true"
            onClick={() => setMobileOpen(false)}
          />

          {/* Menu content */}
          <nav className="relative flex flex-col gap-1 px-4 pt-6" aria-label="Mobil navigasyon">
            {NAV_LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                onClick={() => setMobileOpen(false)}
                className="flex h-12 items-center rounded-lg px-4 text-base font-medium text-muted-foreground transition-colors hover:bg-white/6 hover:text-foreground"
              >
                {link.label}
              </a>
            ))}

            <div className="mt-4 border-t border-border pt-4 flex flex-col gap-2">
              <Link
                href="/auth/login"
                onClick={() => setMobileOpen(false)}
                className="flex h-11 items-center justify-center rounded-lg border border-border text-sm font-medium transition-colors hover:bg-muted"
              >
                Giriş Yap
              </Link>
              <Link
                href="/auth/register"
                onClick={() => setMobileOpen(false)}
                className="flex h-11 items-center justify-center rounded-lg bg-primary text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90"
              >
                Ücretsiz Başla
              </Link>
            </div>
          </nav>
        </div>
      )}
    </>
  );
}
