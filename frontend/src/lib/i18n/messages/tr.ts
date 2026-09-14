import type { MessageTree } from "./en";
import { brand } from "@/lib/branding";

export const tr: MessageTree = {
  product: {
    name: brand.name,
    tagline: "Tüm C-Suite zekası — tek platformda.",
  },
  nav: {
    general: "Genel",
    finance: "Finans",
    analysis: "Analiz",
    csuite: "C-Suite",
    portal: "Portal",
    commandCenter: "Command Center",
    dashboard: "Dashboard",
    upload: "Yükle",
    billing: "Faturalama",
    integrations: "Entegrasyonlar",
    smmm: "Türkiye muhasebe onayı",
    smmmOnay: "SMMM onayları",
  },
  commandCenter: {
    title: "Yönetici Command Center",
    subtitle: "Çok rollü yönetim OS — derinlik veriyi takip eder.",
    generateDeck: "Board deck oluştur",
    conflicts: "Açık çatışmalar",
    turkeyPackHint: "Türkiye paketi açık",
  },
  billing: {
    title: "Planınızı seçin",
    subtitle: "Startup'tan enterprise'a yönetim işletim sistemi.",
    monthly: "Aylık",
    yearly: "Yıllık",
    currentPlan: "Mevcut plan",
    selectPlan: "Planı seç",
    redirecting: "Yönlendiriliyor…",
    managePortal: "Aboneliği yönet",
  },
  upload: {
    title: "Finansal veri yükle",
    subtitle: "CSV, XLSX veya PDF — CFO pipeline ile analiz.",
  },
  empty: {
    noRoleData: "Henüz canlı agent sonucu yok. Veri yükleyin veya analiz çalıştırın.",
    enableDemo: "Demo modunda örnek veri gösterilebilir.",
  },
};
