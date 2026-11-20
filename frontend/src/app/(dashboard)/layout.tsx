"use client";

import { useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { usePathname, useSearchParams } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import { Logo } from "@/components/ui/logo";
import { brand } from "@/lib/branding";
import { DemoBanner } from "@/components/ui/demo-banner";
import { OnboardingBanner } from "@/components/ui/onboarding-banner";
import { SystemStatusWidget } from "@/components/ui/system-status";
import { NotificationBell } from "@/components/ui/notification-bell";
import { ThemeIconToggle } from "@/components/ui/theme-toggle";
import { CommandPaletteTrigger } from "@/components/ui/command-palette";
import { DocumentLang } from "@/components/ui/document-lang";

// PERF: Lazy load heavy overlay components
const AgentChatPanel = dynamic(
  () => import("@/components/ui/agent-chat-panel").then((mod) => mod.AgentChatPanel),
  { ssr: false }
);
const CommandPalette = dynamic(
  () => import("@/components/ui/command-palette").then((mod) => mod.CommandPalette),
  { ssr: false }
);
import {
  LayoutDashboard, Upload, FileText, TrendingUp, DollarSign,
  Menu, X, Clock, CalendarDays, CheckCircle, AlertCircle, Loader2,
  ArrowRightLeft, Waves, ShieldAlert, MessageSquare, Receipt,
  PieChart, BarChart2, Cpu, Crown, Megaphone, Layers, ShieldCheck,
  Users, Shield, FileSearch, FileCheck, Activity, Download,
  LogOut, Building2, ChevronDown, Zap, Link2, CreditCard, Rocket, Filter,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useJobs, useAnomalies } from "@/hooks/useCFO";
import { useOrgSettings } from "@/hooks/useOrgSettings";
import { visibleNavGroups } from "@/lib/nav-focus";
import { useI18n } from "@/hooks/useI18n";

// ── Nav groups ────────────────────────────────────────────────────────────────

const NAV_GROUPS = [
  {
    // The weekly loop in the order it is lived: documents, route, decision, report.
    label: "Hafta",
    items: [
      { href: "/baglan",            label: "Belgeler",         icon: Link2 },
      { href: "/nakit-radari",      label: "Nakit rotası",     icon: Waves },
      { href: "/takvim",            label: "Ödeme takvimi",    icon: CalendarDays },
      { href: "/onay",              label: "Onay bekleyenler", icon: FileCheck },
      { href: "/reports",           label: "Raporlar",         icon: FileText },
      { href: "/settings/workspace", label: "Ayarlar",         icon: Building2 },
    ],
  },
  {
    label: "General",
    items: [
      { href: "/baslangic",     label: "Başlangıç",      icon: Rocket },
      { href: "/command-center", label: "Command Center", icon: Activity },
      { href: "/kurumsallasma",  label: "Kurumsallaşma",  icon: TrendingUp },
      { href: "/iliskili-taraf", label: "İlişkili Taraf",  icon: Users },
      { href: "/pnl",            label: "Dashboard",      icon: LayoutDashboard },
      { href: "/upload",         label: "Upload",         icon: Upload },
    ],
  },
  {
    label: "Finance",
    items: [
      { href: "/pnl",      label: "P&L",       icon: DollarSign },
      { href: "/cashflow", label: "Cash Flow",  icon: Waves },
      { href: "/forecast", label: "Forecast",   icon: TrendingUp },
      { href: "/budget",   label: "Budget",     icon: PieChart },
      { href: "/tax",      label: "Tax",        icon: Receipt },
    ],
  },
  {
    label: "Analytics",
    items: [
      { href: "/trends",                    label: "Trends",          icon: BarChart2 },
      { href: "/anomalies",                 label: "Anomalies",       icon: ShieldAlert },
      { href: "/transactions",              label: "Transactions",    icon: ArrowRightLeft },
      { href: "/analytics/monte-carlo",     label: "Monte Carlo",     icon: TrendingUp },
      { href: "/analytics/working-capital", label: "Working Capital", icon: DollarSign },
      { href: "/analytics/break-even",      label: "Break-Even",      icon: BarChart2 },
      { href: "/analytics/cohort",          label: "Cohort",          icon: Users },
    ],
  },
  {
    label: "C-Suite",
    items: [
      { href: "/cfo",        label: "CFO View",    icon: DollarSign },
      { href: "/cto",        label: "CTO View",    icon: Cpu },
      { href: "/ceo",        label: "CEO View",    icon: Crown },
      { href: "/cmo",        label: "CMO View",    icon: Megaphone },
      { href: "/coo",        label: "COO View",    icon: Layers },
      { href: "/chro",       label: "CHRO View",   icon: Users },
    ],
  },
  {
    label: "Risk & Compliance",
    items: [
      { href: "/risk",         label: "Risk",              icon: Shield },
      { href: "/risk/cascade", label: "Cascade Sim.",      icon: Zap },
      { href: "/compliance",   label: "Compliance",        icon: ShieldCheck },
      { href: "/audit",        label: "Internal Audit",    icon: FileSearch },
      { href: "/sensitivity",  label: "What-If",           icon: Activity },
      { href: "/tetikler",     label: "Tetikler",          icon: Filter },
    ],
  },
  {
    label: "Tools",
    items: [
      { href: "/chat",          label: "CFO Chat",        icon: MessageSquare },
      { href: "/intelligence",  label: "Intelligence",    icon: Activity },
      { href: "/simulation",    label: "Simulation",      icon: Zap },
      { href: "/integrations",  label: "Integrations",    icon: Link2 },
      { href: "/templates",     label: "CSV Templates",   icon: Download },
    ],
  },
  {
    label: "Portal",
    items: [
      { href: "/tr-vertical", label: "TR Autopilot (L3)",        icon: Zap, trPack: true },
      { href: "/smmm",        label: "Turkey accounting review", icon: Users, trPack: true },
      { href: "/smmm-onay",   label: "SMMM approvals",           icon: FileCheck, trPack: true },
      { href: "/billing",     label: "Billing",                  icon: CreditCard },
      { href: "/settings/alerts", label: "Alerts",               icon: Zap },
      { href: "/pilot",       label: "Pilot Program",  icon: Users },
    ],
  },
];

// Flat list for helpers
const allNavItems = NAV_GROUPS.flatMap((g) => g.items);

const STATUS_CONFIG = {
  completed:       { icon: CheckCircle, className: "text-success", label: "Completed" },
  failed:          { icon: AlertCircle, className: "text-destructive",  label: "Failed" },
  pending:         { icon: Loader2,     className: "text-primary animate-spin", label: "Pending" },
  ingesting:       { icon: Loader2,     className: "text-primary animate-spin", label: "Ingesting" },
  analyzing:       { icon: Loader2,     className: "text-primary animate-spin", label: "Analyzing" },
  awaiting_review: { icon: Clock,       className: "text-warning", label: "Review" },
} as const;

// ── User menu ─────────────────────────────────────────────────────────────────

function UserMenu() {
  const { data: session } = useSession();
  const [open, setOpen] = useState(false);

  if (!session) return null;

  const initials = session.user.name
    ? session.user.name.split(" ").map((n: string) => n[0]).join("").slice(0, 2).toUpperCase()
    : session.user.email.slice(0, 2).toUpperCase();

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs transition-colors",
          "hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        )}
        aria-haspopup="true"
        aria-expanded={open}
        aria-label="Kullanıcı menüsü"
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[11px] font-bold text-foreground ring-1 ring-primary/20">
          {initials}
        </span>
        <span className="hidden max-w-[90px] truncate text-xs text-foreground/80 sm:block">
          {session.user.name ?? session.user.email}
        </span>
        <ChevronDown className={cn("h-3 w-3 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden="true" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} aria-hidden="true" />
          <div className="absolute right-0 top-full z-20 mt-1.5 w-56 rounded-xl border border-border bg-card shadow-xl shadow-black/20">
            {/* User info */}
            <div className="border-b border-border px-3 py-3">
              <div className="flex items-center gap-2.5">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-bold text-foreground">
                  {initials}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-xs font-semibold text-foreground">
                    {session.user.name ?? session.user.email}
                  </p>
                  <p className="truncate text-[11px] text-muted-foreground">{session.user.email}</p>
                </div>
              </div>
              <span className="mt-2 inline-flex items-center rounded-md border border-border bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                {session.user.role}
              </span>
            </div>

            <div className="py-1">
              <Link
                href="/settings/workspace"
                onClick={() => setOpen(false)}
                className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <Building2 className="h-3.5 w-3.5" aria-hidden="true" />
                Workspace Ayarları
              </Link>
              <Link
                href="/billing"
                onClick={() => setOpen(false)}
                className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <CreditCard className="h-3.5 w-3.5" aria-hidden="true" />
                Faturalama
              </Link>
            </div>

            <div className="border-t border-border py-1">
              <button
                onClick={() => signOut({ callbackUrl: "/auth/login" })}
                className="flex w-full items-center gap-2 px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
              >
                <LogOut className="h-3.5 w-3.5" aria-hidden="true" />
                Çıkış Yap
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function JobStatusIcon({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status as keyof typeof STATUS_CONFIG] ?? {
    icon: Clock, className: "text-muted-foreground", label: status,
  };
  const Icon = cfg.icon;
  return <Icon className={cn("h-3 w-3 shrink-0", cfg.className)} aria-hidden="true" />;
}

// ── Sidebar content ───────────────────────────────────────────────────────────

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
  const { hasTrPack, focusMode } = useOrgSettings();
  const { t } = useI18n();

  function navHref(href: string) {
    if (jobId && href !== "/upload") return `${href}?job=${jobId}`;
    return href;
  }

  const activeBase = pathname === "/" ? "/" : `/${pathname.split("/")[1]}`;

  const groups = visibleNavGroups(NAV_GROUPS, { hasTrPack, focusMode });

  return (
    <div className="flex h-full flex-col">
      {/* Sidebar header */}
      <div className="flex h-16 shrink-0 items-center px-5">
        <Link href="/" className="rounded-md text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={`${t.product.name} — ana sayfa`}>
          <Logo size="md" />
        </Link>
      </div>

      {/* Nav groups */}
      <nav
        className="flex-1 overflow-y-auto py-3"
        aria-label="Ana gezinme"
        style={{ scrollbarWidth: "none" }}
      >
        {groups.map((group, index) => {
          const hasCurrentPage = group.items.some(({ href }) => activeBase === href || (href !== "/" && pathname.startsWith(href)));

          return (
          <details key={group.label} className="group/nav mb-1" open={hasCurrentPage || index === 0}>
            <summary className="tc-eyebrow mx-2 flex min-h-[36px] cursor-pointer list-none items-center justify-between rounded-md px-2 text-[10px] text-muted-foreground transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden">
              <span>{group.label.toUpperCase()}</span>
              <ChevronDown className="h-3 w-3 transition-transform group-open/nav:rotate-180" aria-hidden="true" />
            </summary>
            <div className="space-y-0.5 px-2 pb-1">
              {group.items.map((navItem) => {
                const { href, label, icon: Icon } = navItem;
                const isActive = activeBase === href || (href !== "/" && pathname.startsWith(href));
                return (
                  <Link
                    key={href}
                    href={navHref(href)}
                    onClick={onNavigate}
                    className={cn(
                      "group relative flex min-h-[44px] items-center gap-2.5 rounded-lg px-3 py-2 text-[14.5px]",
                      "transition-[color,background-color] duration-150 ease-out",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      isActive
                        ? "bg-foreground font-semibold text-background"
                        : "font-normal text-muted-foreground hover:bg-muted hover:text-foreground"
                    )}
                    aria-current={isActive ? "page" : undefined}
                  >
                    <Icon
                      className="h-4 w-4 shrink-0 text-current opacity-90"
                      aria-hidden="true"
                    />

                    <span className="flex-1 truncate">{label}</span>

                    {href === "/anomalies" && anomalyCritical > 0 && (
                      <span
                        className="rounded-full bg-destructive px-1.5 py-0.5 text-[10px] font-bold text-destructive-foreground"
                        aria-label={`${anomalyCritical} kritik anomali`}
                      >
                        {anomalyCritical}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          </details>
          );
        })}

        {/* Recent analyses */}
        {jobs && jobs.length > 0 && (
          <div className="mb-2 mt-4 px-2">
            <p className="tc-eyebrow mb-1 px-3 text-[10px] text-muted-foreground">
              Son Analizler
            </p>
            <div className="space-y-0.5">
              {jobs.slice(0, 6).map((job) => {
                const isActive = jobId === job.job_id;
                return (
                  <Link
                    key={job.job_id}
                    href={`/?job=${job.job_id}`}
                    onClick={onNavigate}
                    className={cn(
                      "flex items-center gap-2 rounded-lg px-3 py-1.5 transition-colors",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      isActive ? "bg-muted" : "hover:bg-muted"
                    )}
                    title={job.filename}
                  >
                    <JobStatusIcon status={job.status} />
                    <span className={cn(
                      "flex-1 truncate text-xs",
                      isActive ? "font-medium text-foreground" : "text-muted-foreground"
                    )}>
                      {job.filename}
                    </span>
                  </Link>
                );
              })}
            </div>
          </div>
        )}
      </nav>

      {/* Sidebar footer */}
      <div className="shrink-0 border-t border-border p-3">
        <Link
          href="/billing"
          className="flex min-h-[44px] items-center gap-2.5 rounded-lg border border-border px-3 py-2 transition-colors hover:bg-muted"
        >
          <Zap className="h-4 w-4 text-primary" aria-hidden="true" />
          <div className="min-w-0">
            <p className="text-xs font-semibold text-foreground">Planı yükselt</p>
            <p className="text-[10px] text-muted-foreground">Tüm yönetim görünümleri</p>
          </div>
        </Link>
      </div>
    </div>
  );
}

// ── Breadcrumb ────────────────────────────────────────────────────────────────

function Breadcrumb({ pathname }: { pathname: string }) {
  const activeBase = pathname === "/" ? "/" : `/${pathname.split("/")[1]}`;
  const current = allNavItems.find((item) => item.href === activeBase || item.href === pathname);
  if (!current || pathname === "/") return null;

  return (
    <nav aria-label="Breadcrumb" className="hidden items-center gap-1.5 text-xs text-muted-foreground sm:flex">
      <Link href="/" className="transition-colors hover:text-foreground">
        Dashboard
      </Link>
      <span aria-hidden="true">/</span>
      <span className="font-medium text-foreground">{current.label}</span>
    </nav>
  );
}

// ── Layout ────────────────────────────────────────────────────────────────────

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
      <DocumentLang />

      {/* Desktop sidebar */}
      <aside
        className="dark hidden w-64 shrink-0 border-r border-border bg-background text-foreground lg:flex lg:flex-col"
        aria-label="Sidebar navigation"
      >
        <SidebarContent pathname={pathname} jobId={jobId} />
      </aside>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-background/80 backdrop-blur lg:hidden"
          aria-hidden="true"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Mobile drawer */}
      <aside
        className={cn(
          "dark fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r border-border bg-background text-foreground",
          "transition-transform duration-200 ease-out lg:hidden",
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
        aria-label="Mobile navigation"
      >
        <button
          onClick={() => setMobileOpen(false)}
          className="absolute right-3 top-3 rounded-md p-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Menüyü kapat"
        >
          <X className="h-4 w-4" />
        </button>
        <SidebarContent pathname={pathname} jobId={jobId} onNavigate={() => setMobileOpen(false)} />
      </aside>

      {/* Main content */}
      <div className="flex min-w-0 flex-1 flex-col">

        {/* Demo/onboarding banners */}
        {process.env.NEXT_PUBLIC_DEMO_MODE === "true" && <DemoBanner />}
        <OnboardingBanner />

        {/* Top bar */}
        <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-background/90 px-4 backdrop-blur-md sm:px-5">

          {/* Mobile hamburger */}
          <button
            onClick={() => setMobileOpen(true)}
            className="rounded-md p-1.5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:hidden"
            aria-label="Menüyü aç"
          >
            <Menu className="h-4 w-4" />
          </button>

          {/* Logo (mobile only — desktop sidebar has it) */}
          <Link href="/" className="flex items-center lg:hidden">
            <Logo size="sm" />
          </Link>

          {/* Breadcrumb (desktop) */}
          <div className="hidden flex-1 lg:block">
            <Breadcrumb pathname={pathname} />
          </div>

          {/* Command palette trigger */}
          <div className="flex flex-1 justify-center px-4 lg:flex-none lg:justify-start">
            <CommandPaletteTrigger className="w-full max-w-xs" />
          </div>

          {/* Right actions */}
          <div className="ml-auto flex items-center gap-1.5">
            <div className="hidden sm:block">
              <SystemStatusWidget variant="inline" />
            </div>
            <ThemeIconToggle />
            <NotificationBell />
            <UserMenu />
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto">
          {children}
        </main>

        {/* Global overlays */}
        <CommandPalette />
        <AgentChatPanel agentFilter="all" agentLabel={`${brand.name} AI`} />
      </div>
    </div>
  );
}
