"use client";

import { useState } from "react";
import { FileText, ChevronLeft, ChevronRight } from "lucide-react";
import { formatPercent } from "@/lib/dashboard-utils";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/hooks/useI18n";
import { type BoardSlide, fmt } from "./types";

interface BoardDeckViewerProps {
  slides: BoardSlide[];
}

export function BoardDeckViewer({ slides }: BoardDeckViewerProps) {
  const [currentSlide, setCurrentSlide] = useState(0);
  const { t } = useI18n();
  const slide = slides[currentSlide];

  const goNext = () => setCurrentSlide((prev) => (prev + 1) % slides.length);
  const goPrev = () =>
    setCurrentSlide((prev) => (prev - 1 + slides.length) % slides.length);

  if (!slide) return null;

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold">
        <FileText className="h-4 w-4" aria-hidden="true" />
        {t.boardDeck.title}
      </h3>

      <div className="mb-4 flex aspect-video flex-col justify-between rounded bg-muted p-6">
        <div>
          <p className="mb-2 text-xs text-muted-foreground">
            {t.boardDeck.slide} {slide.slide_number} / {slides.length}
          </p>
          <h2 className="mb-2 text-2xl font-bold">{slide.title}</h2>
          <p className="text-sm text-muted-foreground">{slide.content}</p>
        </div>

        {slide.metrics && (
          <div className="mt-4 grid grid-cols-3 gap-2">
            {Object.entries(slide.metrics)
              .slice(0, 3)
              .map(([key, value]) => (
                <div key={key} className="rounded bg-background/50 p-2">
                  <p className="text-xs capitalize text-muted-foreground">
                    {key.replace(/_/g, " ")}
                  </p>
                  <p className="font-semibold">
                    {typeof value === "number" && value < 1
                      ? formatPercent(value)
                      : fmt(value, 1)}
                  </p>
                </div>
              ))}
          </div>
        )}
      </div>

      <div className="flex items-center justify-between">
        <Button variant="outline" size="icon" onClick={goPrev} aria-label={t.boardDeck.previous}>
          <ChevronLeft className="h-4 w-4" />
        </Button>

        <div className="flex gap-1" role="tablist" aria-label={t.boardDeck.navigation}>
          {slides.map((_, i) => (
            <button
              key={i}
              role="tab"
              aria-selected={i === currentSlide}
              aria-label={t.boardDeck.goTo.replace("{n}", String(i + 1))}
              onClick={() => setCurrentSlide(i)}
              className={`h-2 rounded-full transition ${
                i === currentSlide
                  ? "w-4 bg-primary"
                  : "w-2 bg-muted hover:bg-muted-foreground"
              }`}
            />
          ))}
        </div>

        <Button variant="outline" size="icon" onClick={goNext} aria-label={t.boardDeck.next}>
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
