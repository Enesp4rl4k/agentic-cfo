"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import { Logo } from "@/components/ui/logo";
import { DemoBanner } from "@/components/ui/demo-banner";
import { OnboardingBanner } from "@/components/ui/onboarding-banner";
import { SystemStatusWidget } from "@/components/ui/system-status";
import {
  LayoutDashboard,
  Upload,
  FileText,
  TrendingUp,
  DollarSign,
  Menu,
  X,
  Clock,
  CheckCircle,
  AlertCircle,
  Loader2,
  ArrowRightLeft,
  Waves,
  ShieldAlert,
  MessageSquare,
  Receipt,
  PieChart,
  BarChart2,
  Cpu,
  Crown,
  Megaphone,
  Layers,
  ShieldCheck,
  Users,
  Shield,
  FileSearch,
  Activity,
  Download,
  LogOut,
  Building2,
  ChevronDown,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useJobs, useAnomalies } from "@/hooks/useCFO";

const navItems = [
  // ── Command Center
  { href: "/command-center", label: "Command Center", icon: Activity },
  // ── Ana görünümler
  { href: "/",            label: "Dashboard",   icon: LayoutDashboard },
  { href: "/upload",      label: "Upload",      icon: Upload },
  // ── Finansal tablolar
  { href: "/pnl",         label: "P&L",         icon: DollarSign },
  { href: "/cashflow",    label: "Cash Flow",   icon: Waves },
  { href: "/forecast",    label: "Forecast",    icon: TrendingUp },
  // ── Gelişmiş analiz
  { href: "/budget",      label: "Budget",      icon: PieChart },
  { href: "/tax",         label: "Tax",         icon: Receipt },
  { href: "/trends",      label: "Trends",      icon: BarChart2 },
  { href: "/anomalies",   label: "Anomalies",   icon: ShieldAlert },
  // ── İşlemler & AI
  { href: "/transactions", label: "Transactions", icon: ArrowRightLeft },
  { href: "/chat",        label: "CFO Chat",    icon: MessageSquare },
  { href: "/reports",     label: "Reports",     icon: FileText },
  // ── Kurumsal Yönetim
  { href: "/cto",         label: "CTO View",    icon: Cpu },
  { href: "/ceo",         label: "CEO View",    icon: Crown },
  { href: "/cmo",         label: "CMO View",    icon: Megaphone },
  { href: "/coo",         label: "COO View",    icon: Layers },
  { href: "/chro",        label: "CHRO View",   icon: Users },
  { href: "/compliance",  label: "Compliance",  icon: ShieldCheck },
  { href: "/risk",        label: "Risk",        icon: Shield },
  { href: "/audit",       label: "Internal Audit", icon: FileSearch },
  // ── Tools
  { href: "/templates",   label: "CSV Templates", icon: Download },
  // ── Ayarlar & Admin
  { href: "/settings/workspace", label: "Workspace",  icon: Building2 },
  { href: "/pilot",              label: "Pilot Program", icon: Users },
];

const STATUS_CONFIG = {
  completed: {
    icon: CheckCircle,
    className: "text-emerald-400",
    label: "Completed",
  },
  failed: {
    icon: AlertCircle,
    className: "text-destructive",
    label: "Failed",
  },
  pending: {
    icon: Loader2,
    className: "text-primary animate-spin",
    label: "Pending",
  },
  ingesting: {
    icon: Loader2,
    className: "text-primary animate-spin",
    label: "Ingesting",
  },
  analyzing: {
    icon: Loader2,
    className: "text-primary animate-spin",
    label: "Analyzing",
  },
  awaiting_review: {
    icon: Clock,
    className: "text-warning",
    label: "Review",
  },
} as const;

// ── User menu ─────────────────────────────────────────────────────────────────

function UserMenu() {
  const { data: session } = useSession();
  const [open, setOpen] = useState(false);

  if (!session) return null;

  const initials = session.user.name
    ? session.user.name.split(" ").map((n) => n[0]).join("").slice(0, 2).toUpperCase()
    : session.user.email.slice(0, 2).toUpperCase();

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center gap-2 rounded-md px-2 py-1.5 text-xs transition-colors",
          "hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        )}
        aria-haspopup="true"
        aria-expanded={open}
      >
        {/* Avatar */}
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[10px] font-semibold text-primary">
          {initials}
        </span>
        <span className="hidden max-w-[100px] truncate sm:block text-xs text-foreground">
          {session.user.name ?? session.user.email}
        </span>
        <ChevronDown className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} aria-hidden="true" />
          <div className="absolute right-0 top-full z-20 mt-1 w-56 rounded-lg border border-border bg-card py-1 shadow-lg">
            {/* User info */}
            <div className="border-b border-border px-3 py-2.5">
              <p className="text-xs font-medium truncate">{session.user.name ?? session.user.email}</p>
              <p className="mt-0.5 text-xs text-muted-foreground truncate">{session.user.email}</p>
              {(session.user as any).orgId && (
                <p className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground">
                  <Building2 className="h-3 w-3" aria-hidden="true" />
                  Workspace üyesi
                </p>
              )}
              <span className="mt-1 inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-muted text-muted-foreground">
                {session.user.role}
              </span>
            </div>

            {/* Actions */}
            <Link
              href="/settings/workspace"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <Building2 className="h-3.5 w-3.5" aria-hidden="true" />
              Workspace Ayarları
            </Link>

            <button
              onClick={() => signOut({ callbackUrl: "/auth/login" })}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
            >
              <LogOut className="h-3.5 w-3.5" aria-hidden="true" />
              Çıkış Yap
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function JobStatusIcon({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status as keyof typeof STATUS_CONFIG] ?? {
    icon: Clock,
    className: "text-muted-foreground",
    label: status,
  };
  const Icon = cfg.icon;
  return <Icon className={cn("h-3 w-3 shrink-0", cfg.className)} aria-hidden="true" />;
}

function SidebarContent({
  pathname,
  jobId,
  onNavigate,
}: {
  pathname: string;
  jobId: string | null;
  onNavigate?: () => void;
}) {
  const { data: jobs } = useJobs();
  const { data: anomalyData } = useAnomalies(jobId);
  const anomalyCritical = anomalyData?.critical ?? 0;

  function navHref(href: string) {
    if (jobId && href !== "/upload") return `${href}?job=${jobId}`;
    return href;
  }

  const activeBase = pathname === "/" ? "/" : `/${pathname.split("/")[1]}`;

  return (
    <>
      {/* Logo */}
      <div className="flex h-14 items-center gap-2 border-b border-border px-5">
        <Crown className="h-5 w-5 text-primary" aria-hidden="true" />
        <span className="font-semibold tracking-tight">AI Suite</span>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-0.5 overflow-y-auto p-3" aria-label="Main navigation">
        {navItems.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={navHref(href)}
            onClick={onNavigate}
            className={cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              activeBase === href
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            )}
            aria-current={activeBase === href ? "page" : undefined}
          >
            <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span className="flex-1">{label}</span>
            {href === "/anomalies" && anomalyCritical > 0 && (
              <span
                className="rounded-full bg-destructive px-1.5 py-0.5 text-[10px] font-semibold text-destructive-foreground"
                aria-label={`${anomalyCritical} critical anomalies`}
              >
                {anomalyCritical}
              </span>
            )}
          </Link>
        ))}

        {/* Recent analyses */}
        {jobs && jobs.length > 0 && (
          <div className="mt-4 px-1">
            <p className="mb-1.5 px-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Recent Analyses
            </p>
            <div className="space-y-0.5">
              {jobs.slice(0, 8).map((job) => {
                const isActive = jobId === job.job_id;
                return (
                  <Link
                    key={job.job_id}
                    href={`/?job=${job.job_id}`}
                    onClick={onNavigate}
                    className={cn(
                      "flex items-center gap-2 rounded-md px-2 py-1.5 transition-colors",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      isActive
                        ? "bg-primary/10"
                        : "hover:bg-muted"
                    )}
                    title={job.filename}
                  >
                    <JobStatusIcon status={job.status} />
                    <span
                      className={cn(
                        "flex-1 truncate text-xs",
                        isActive ? "font-medium text-primary" : "text-muted-foreground"
                      )}
                    >
                      {job.filename}
                    </span>
                  </Link>
                );
              })}
            </div>
          </div>
        )}
      </nav>

      <div className="border-t border-border p-4">
        <Logo size="sm" />
      </div>
    </>
  );
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex min-h-screen bg-background">
      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 border-r border-border bg-card lg:flex lg:flex-col">
        <SidebarContent pathname={pathname} jobId={jobId} />
      </aside>

      {/* Mobile sidebar overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-background/80 backdrop-blur lg:hidden"
          aria-hidden="true"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Mobile sidebar drawer */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-border bg-card",
          "transition-transform duration-200 ease-out lg:hidden",
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
        aria-label="Mobile navigation"
      >
        <div className="absolute right-3 top-3">
          <button
            onClick={() => setMobileOpen(false)}
            className="rounded-md p-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Close menu"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <SidebarContent
          pathname={pathname}
          jobId={jobId}
          onNavigate={() => setMobileOpen(false)}
        />
      </aside>

      {/* Main content */}
    <div className="flex flex-1 flex-col min-w-0">
      {/* Demo banner — shown only in demo mode */}
      {process.env.NEXT_PUBLIC_DEMO_MODE === "true" && <DemoBanner />}

      {/* Onboarding banner — shown until dismissed */}
      <OnboardingBanner />

      {/* Top bar */}
      <header className="sticky top-0 z-10 flex h-14 items-center gap-3 border-b border-border bg-background/80 px-4 backdrop-blur sm:px-6">
        {/* Mobile menu button */}
        <button
          onClick={() => setMobileOpen(true)}
          className="rounded-md p-1.5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:hidden"
          aria-label="Open menu"
        >
          <Menu className="h-4 w-4" />
        </button>
        <Link href="/" className="flex items-center">
          <Logo size="sm" />
        </Link>
        <div className="ml-auto flex items-center gap-3">
          <div className="hidden sm:block">
            <SystemStatusWidget variant="inline" />
          </div>
          <UserMenu />
        </div>
      </header>

      <main className="flex-1 overflow-auto">{children}</main>
    </div>
    </div>
  );
}
