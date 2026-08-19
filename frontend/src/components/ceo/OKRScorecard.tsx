"use client";

import { TrendingUp, Target } from "lucide-react";
import { formatPercent } from "@/lib/dashboard-utils";
import { type OKRObjective, fmt } from "./types";

interface OKRScorecardProps {
  objectives: OKRObjective[];
  companyScore: number;
}

function getMomentumIcon(momentum: string) {
  switch (momentum) {
    case "up":
      return <TrendingUp className="h-4 w-4 text-green-400" aria-label="Trending up" />;
    case "down":
      return (
        <TrendingUp
          className="h-4 w-4 rotate-180 text-red-400"
          aria-label="Trending down"
        />
      );
    default:
      return <span className="h-4 w-4 text-yellow-400" aria-label="Stable">—</span>;
  }
}

export function OKRWeightedScorecard({ objectives, companyScore }: OKRScorecardProps) {
  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <div className="mb-6 flex items-end justify-between">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Target className="h-4 w-4" aria-hidden="true" />
          OKR Ağırlıklı Puan Kartı
        </h3>
        <div className="text-right">
          <p className="mb-1 text-xs text-muted-foreground">Şirket Puanı</p>
          <p className="text-3xl font-bold">{fmt(companyScore * 100, 0)}%</p>
        </div>
      </div>

      <div className="space-y-4">
        {objectives.map((obj) => {
          const weightedScore = obj.score * obj.weight;
          return (
            <div
              key={obj.objective_id}
              className="rounded border border-border bg-muted/20 p-4"
            >
              <div className="mb-2 flex items-start justify-between">
                <div className="flex-1">
                  <div className="mb-1 flex items-center gap-2">
                    <h4 className="text-sm font-medium">{obj.name}</h4>
                    {getMomentumIcon(obj.momentum)}
                  </div>
                  <div className="flex gap-2 text-xs text-muted-foreground">
                    <span>Ağırlık: {formatPercent(obj.weight)}</span>
                    <span>Puan: {fmt(obj.score * 100, 0)}%</span>
                    <span className="font-semibold">
                      Ağ. Puan: {fmt(weightedScore * 100, 0)}%
                    </span>
                  </div>
                </div>
              </div>

              {/* Progress bar */}
              <div
                className="mb-2 h-2 w-full overflow-hidden rounded bg-muted"
                role="progressbar"
                aria-valuenow={Math.round(obj.score * 100)}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <div
                  className="h-full rounded bg-gradient-to-r from-blue-500 to-purple-500"
                  style={{ width: `${obj.score * 100}%` }}
                />
              </div>

              {/* Key Results */}
              <div className="space-y-1">
                {obj.key_results.map((kr, idx) => (
                  <div key={idx} className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">{kr.name}</span>
                    <span className="font-medium">{formatPercent(kr.progress)}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Summary */}
      <div className="mt-6 border-t border-border pt-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded bg-muted/30 p-2">
            <p className="mb-1 text-xs text-muted-foreground">Ortalama Puan</p>
            <p className="text-lg font-bold">
              {fmt(
                (objectives.reduce((sum, o) => sum + o.score, 0) /
                  objectives.length) *
                  100,
                0
              )}%
            </p>
          </div>
          <div className="rounded bg-muted/30 p-2">
            <p className="mb-1 text-xs text-muted-foreground">Ağırlıklı Ortalama</p>
            <p className="text-lg font-bold">{fmt(companyScore * 100, 0)}%</p>
          </div>
        </div>
      </div>
    </div>
  );
}
