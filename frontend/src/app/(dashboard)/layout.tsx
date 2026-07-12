"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Upload,
  FileText,
  TrendingUp,
  DollarSign,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/upload", label: "Upload", icon: Upload },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/forecast", label: "Forecast", icon: TrendingUp },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen bg-background">
      {/* Sidebar */}
      <aside className="hidden w-60 shrink-0 border-r border-border bg-card lg:flex lg:flex-col">
        {/* Logo */}
        <div className="flex h-14 items-center gap-2 border-b border-border px-5">
          <DollarSign className="h-5 w-5 text-primary" aria-hidden="true" />
          <span className="font-semibold tracking-tight">AI CFO</span>
        </div>

        {/* Nav */}
        <nav className="flex-1 space-y-1 p-3" aria-label="Main navigation">
          {navItems.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                pathname === href
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
              aria-current={pathname === href ? "page" : undefined}
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              {label}
            </Link>
          ))}
        </nav>

        <div className="border-t border-border p-4">
          <p className="text-xs text-muted-foreground">
            Powered by GPT-4o + LangGraph
          </p>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex flex-1 flex-col">
        {/* Top bar */}
        <header className="sticky top-0 z-10 flex h-14 items-center border-b border-border bg-background/80 px-6 backdrop-blur">
          <h1 className="text-sm font-semibold text-muted-foreground">
            Financial Intelligence Platform
          </h1>
        </header>

        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
