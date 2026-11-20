/**
 * The menu (plan v11 A0.6, G16). Group and item labels are i18n keys, never copy:
 * the sidebar and the breadcrumb read `t.menu.groups[label]` and `t.menu.items[labelKey]`.
 * `label` on a group is its stable id; focus mode (lib/nav-focus) filters by href.
 */
import {
  Activity, ArrowRightLeft, BarChart2, Building2, Cpu, CreditCard, Crown, DollarSign, Download, FileCheck, FileSearch, FileText, Filter, Layers, LayoutDashboard, Link2, Megaphone, MessageSquare, Newspaper, PieChart, Receipt, Rocket, Shield, ShieldAlert, ShieldCheck, TrendingUp, Upload, Users, Waves, Zap,
} from "lucide-react";
import type { MessageTree } from "@/lib/i18n";

export type MenuGroupKey = keyof MessageTree["menu"]["groups"];
export type MenuItemKey = keyof MessageTree["menu"]["items"];

export const NAV_GROUPS: {
  label: MenuGroupKey;
  items: { href: string; labelKey: MenuItemKey; icon: typeof Rocket; trPack?: boolean }[];
}[] = [
  {
    label: "general",
    items: [
      { href: "/baslangic", labelKey: "baslangic",      icon: Rocket },
      { href: "/command-center", labelKey: "commandCenter", icon: Activity },
      { href: "/nakit-radari", labelKey: "nakitRadari",   icon: Waves },
      { href: "/bulten", labelKey: "bulten", icon: Newspaper },
      { href: "/kurumsallasma", labelKey: "kurumsallasma",  icon: TrendingUp },
      { href: "/iliskili-taraf", labelKey: "iliskiliTaraf",  icon: Users },
      { href: "/pnl", labelKey: "dashboard",      icon: LayoutDashboard },
      { href: "/baglan", labelKey: "baglan", icon: Link2 },
      { href: "/upload", labelKey: "upload",         icon: Upload },
    ],
  },
  {
    label: "finance",
    items: [
      { href: "/pnl", labelKey: "pnl",       icon: DollarSign },
      { href: "/cashflow", labelKey: "cashflow",  icon: Waves },
      { href: "/forecast", labelKey: "forecast",   icon: TrendingUp },
      { href: "/budget", labelKey: "budget",     icon: PieChart },
      { href: "/tax", labelKey: "tax",        icon: Receipt },
    ],
  },
  {
    label: "analytics",
    items: [
      { href: "/trends", labelKey: "trends",          icon: BarChart2 },
      { href: "/anomalies", labelKey: "anomalies",       icon: ShieldAlert },
      { href: "/transactions", labelKey: "transactions",    icon: ArrowRightLeft },
      { href: "/analytics/monte-carlo", labelKey: "monteCarlo",     icon: TrendingUp },
      { href: "/analytics/working-capital", labelKey: "workingCapital", icon: DollarSign },
      { href: "/analytics/break-even", labelKey: "breakEven",      icon: BarChart2 },
      { href: "/analytics/cohort", labelKey: "cohort",          icon: Users },
    ],
  },
  {
    label: "csuite",
    items: [
      { href: "/cfo", labelKey: "cfo",    icon: DollarSign },
      { href: "/cto", labelKey: "cto",    icon: Cpu },
      { href: "/ceo", labelKey: "ceo",    icon: Crown },
      { href: "/cmo", labelKey: "cmo",    icon: Megaphone },
      { href: "/coo", labelKey: "coo",    icon: Layers },
      { href: "/chro", labelKey: "chro",   icon: Users },
    ],
  },
  {
    label: "risk",
    items: [
      { href: "/risk", labelKey: "risk",              icon: Shield },
      { href: "/risk/cascade", labelKey: "cascade",      icon: Zap },
      { href: "/compliance", labelKey: "compliance",        icon: ShieldCheck },
      { href: "/audit", labelKey: "audit",    icon: FileSearch },
      { href: "/sensitivity", labelKey: "sensitivity",           icon: Activity },
      { href: "/tetikler", labelKey: "tetikler",          icon: Filter },
    ],
  },
  {
    label: "tools",
    items: [
      { href: "/chat", labelKey: "chat",        icon: MessageSquare },
      { href: "/reports", labelKey: "reports",         icon: FileText },
      { href: "/intelligence", labelKey: "intelligence",    icon: Activity },
      { href: "/simulation", labelKey: "simulation",      icon: Zap },
      { href: "/integrations", labelKey: "integrations",    icon: Link2 },
      { href: "/templates", labelKey: "templates",   icon: Download },
    ],
  },
  {
    label: "portal",
    items: [
      { href: "/tr-vertical", labelKey: "trVertical",        icon: Zap, trPack: true },
      { href: "/smmm", labelKey: "smmm", icon: Users, trPack: true },
      { href: "/smmm-onay", labelKey: "smmmOnay",           icon: FileCheck, trPack: true },
      { href: "/billing", labelKey: "billing",                  icon: CreditCard },
      { href: "/settings/alerts", labelKey: "alerts",               icon: Zap },
      { href: "/settings/workspace", labelKey: "workspace", icon: Building2 },
      { href: "/pilot", labelKey: "pilot",  icon: Users },
    ],
  },
];
