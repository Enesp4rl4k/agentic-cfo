import { brand } from "@/lib/branding";

export type MessageTree = {
  product: {
    name: string;
    tagline: string;
  };
  nav: {
    general: string;
    finance: string;
    analysis: string;
    csuite: string;
    portal: string;
    commandCenter: string;
    dashboard: string;
    upload: string;
    billing: string;
    integrations: string;
    smmm: string;
    smmmOnay: string;
  };
  commandCenter: {
    title: string;
    subtitle: string;
    generateDeck: string;
    conflicts: string;
    turkeyPackHint: string;
  };
  billing: {
    title: string;
    subtitle: string;
    monthly: string;
    yearly: string;
    currentPlan: string;
    selectPlan: string;
    redirecting: string;
    managePortal: string;
  };
  upload: {
    title: string;
    subtitle: string;
  };
  empty: {
    noRoleData: string;
    enableDemo: string;
  };
};

export const en: MessageTree = {
  product: {
    name: brand.name,
    tagline: "Your entire C-Suite, powered by AI — globally.",
  },
  nav: {
    general: "General",
    finance: "Finance",
    analysis: "Analytics",
    csuite: "C-Suite",
    portal: "Portal",
    commandCenter: "Command Center",
    dashboard: "Dashboard",
    upload: "Upload",
    billing: "Billing",
    integrations: "Integrations",
    smmm: "Turkey accounting review",
    smmmOnay: "SMMM approvals",
  },
  commandCenter: {
    title: "Executive Command Center",
    subtitle: "Multi-role management OS — depth follows your data.",
    generateDeck: "Generate board deck",
    conflicts: "Open conflicts",
    turkeyPackHint: "Turkey pack enabled",
  },
  billing: {
    title: "Choose your plan",
    subtitle: "A management operating system, from startup to enterprise.",
    monthly: "Monthly",
    yearly: "Yearly",
    currentPlan: "Current plan",
    selectPlan: "Select plan",
    redirecting: "Redirecting…",
    managePortal: "Manage subscription",
  },
  upload: {
    title: "Upload financial data",
    subtitle: "CSV, XLSX, or PDF — analyzed by the CFO pipeline.",
  },
  empty: {
    noRoleData: "No live agent results yet. Upload data or run an analysis.",
    enableDemo: "Demo mode can show sample data when enabled.",
  },
};
