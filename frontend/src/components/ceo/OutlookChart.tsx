"use client";

import { TrendingUp } from "lucide-react";
import {
  Area,
  ComposedChart,
  CartesianGrid,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { type CEOOutlook } from "./types";

const MONTHS = ["Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara", "Oca", "Şub", "Mar", "Nis", "May", "Haz"];

interface OutlookChartProps {
  outlook: CEOOutlook;
}

export function OutlookChart({ outlook }: OutlookChartProps) {
  const data = MONTHS.map((month, i) => ({
    month,
    base:        outlook.base_case[i]   ?? 0,
    optimistic:  outlook.optimistic[i]  ?? 0,
    pessimistic: outlook.pessimistic[i] ?? 0,
  }));

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold">
        <TrendingUp className="h-4 w-4" aria-hidden="true" />
        12 Aylık Outlook (Senaryo Bantları)
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.1} />
          <XAxis dataKey="month" stroke="currentColor" opacity={0.5} />
          <YAxis stroke="currentColor" opacity={0.5} />
          <Tooltip contentStyle={{ backgroundColor: "transparent", border: "none" }} />
          <Legend />
          <Area
            type="monotone"
            dataKey="optimistic"
            fill="#10b981"
            stroke="#10b981"
            fillOpacity={0.2}
            name="İyimser"
          />
          <Line
            type="monotone"
            dataKey="base"
            stroke="#3b82f6"
            strokeWidth={2}
            name="Temel"
          />
          <Area
            type="monotone"
            dataKey="pessimistic"
            fill="#ef4444"
            stroke="#ef4444"
            fillOpacity={0.2}
            name="Kötümser"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
