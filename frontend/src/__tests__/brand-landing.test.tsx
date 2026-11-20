/**
 * Brand landing (Tunç Çağı): what a visitor and a keyboard user get.
 *
 * Checks the page's contract, not its pixels: the first screen names what is
 * sold and for whom, the tour is a real ARIA tab set, no placeholder text
 * ships, every link lands, and the sample figures stay consistent with the
 * route the product shows. Browser-only things (layout, motion, contrast) are
 * checked in a real browser, not here.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BrandLanding } from "@/components/brand-landing/BrandLanding";
import { curvePoint, formatTry, sampleClose, tabOrder } from "@/components/brand-landing/content";
import { flashLevel, frame, lightningBolt, waveAt } from "@/components/brand-landing/storm";
import { getMessages } from "@/lib/i18n";

// The real button mints a guest session and needs the app's providers; its own
// behaviour is covered in demo-guest.test.tsx. Here only its door on the page matters.
vi.mock("@/components/demo/GuestDemoButton", () => ({
  GuestDemoButton: ({ children, className }: { children: React.ReactNode; className?: string }) => (
    <button type="button" className={className}>
      {children}
    </button>
  ),
}));

const m = getMessages("tr").brandLanding;
const en = getMessages("en").brandLanding;

beforeEach(() => {
  // Reduced motion: the storm scene paints one still frame and starts no loop.
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("reduce"),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    onchange: null,
    dispatchEvent: vi.fn(),
  }));
});

describe("Brand landing: first screen", () => {
  it("names the category and the buyer in the h1, with the storm line second", () => {
    render(<BrandLanding />);
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1).toHaveTextContent("Şirketlerin nakit rotası, kendi belgelerinden çizilir");
    expect(screen.getByText(m.hero.tagline)).toBeInTheDocument();
    expect(screen.getByText(m.hero.eyebrow)).toBeInTheDocument();
  });

  it("renders in English for an English visitor, with nothing left in Turkish", () => {
    const { container } = render(<BrandLanding locale="en" />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("A company's cash route, drawn from your own documents");
    expect(screen.getByRole("tablist", { name: en.product.tablistLabel })).toBeInTheDocument();
    // The skip link and the sample caption are the cheapest places a stray Turkish string would show.
    expect(container.querySelector("a")).toHaveTextContent(en.skip);
    expect(container.textContent).toContain(en.footer.sample);
    expect(container.textContent).not.toContain(m.footer.sample);
  });

  it("does not promise a fixed horizon or a family-only buyer in the h1", () => {
    render(<BrandLanding />);
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).not.toMatch(/\d+\s*hafta|aile/i);
  });

  it("speaks of trust as a promise, never by naming the doubt", () => {
    for (const locale of ["tr", "en"] as const) {
      const { container, unmount } = render(<BrandLanding locale={locale} />);
      expect(container.textContent).not.toMatch(/uydurul|truva|yeniden çizilir|made-up|trojan|redrawn/i);
      unmount();
    }
  });

  it("has two hero actions at most, each a verb and an object", () => {
    render(<BrandLanding />);
    const hero = screen.getByRole("heading", { level: 1 }).closest("section");
    expect(hero).not.toBeNull();
    const actions = within(hero as HTMLElement).getAllByRole("link");
    expect(actions).toHaveLength(2);
    expect(actions[0]).toHaveTextContent("Kasamı göster");
    expect(actions[0]).toHaveAttribute("href", "/auth/register");
  });

  it("keeps a door to the guest demo on the homepage, outside the hero's two actions", () => {
    render(<BrandLanding />);
    expect(screen.getByRole("button", { name: m.close.demo })).toBeInTheDocument();
    const hero = screen.getByRole("heading", { level: 1 }).closest("section") as HTMLElement;
    expect(within(hero).queryByRole("button", { name: m.close.demo })).toBeNull();
  });

  it("upper-cases the wordmark by the Latin rule, with no dotted İ", () => {
    const { container } = render(<BrandLanding />);
    const marks = Array.from(container.querySelectorAll("a[href='/'] span:last-child"));
    expect(marks.length).toBeGreaterThan(0);
    for (const mark of marks) {
      expect(mark.textContent).toBe(mark.textContent?.toLocaleUpperCase("en-US"));
      expect(mark.textContent).not.toContain("İ");
    }
  });

  it("links the wordmark to the homepage", () => {
    render(<BrandLanding />);
    expect(screen.getAllByRole("link", { name: /ana sayfa/ })[0]).toHaveAttribute("href", "/");
  });

  it("describes the storm scene for a screen reader", () => {
    render(<BrandLanding />);
    expect(screen.getByRole("img", { name: /Fırtınalı denizde/ })).toBeInTheDocument();
  });
});

describe("Brand landing: keyboard and structure", () => {
  it("puts the skip link first and it lands on the main content", () => {
    const { container } = render(<BrandLanding />);
    const first = container.querySelector("a");
    expect(first).toHaveTextContent(m.skip);
    expect(first).toHaveAttribute("href", "#icerik");
    expect(container.querySelector("#icerik")).not.toBeNull();
  });

  it("gives every link a name and a real target", () => {
    render(<BrandLanding />);
    for (const link of screen.getAllByRole("link")) {
      expect(link.textContent?.trim() || link.getAttribute("aria-label")).toBeTruthy();
      const href = link.getAttribute("href");
      expect(href).toBeTruthy();
      expect(href).not.toBe("#");
    }
  });

  it("keeps heading levels one step at a time", () => {
    const { container } = render(<BrandLanding />);
    const levels = Array.from(container.querySelectorAll("h1,h2,h3")).map((h) => Number(h.tagName[1]));
    expect(levels[0]).toBe(1);
    levels.slice(1).forEach((level, i) => {
      expect(level - levels[i]).toBeLessThanOrEqual(1);
    });
  });

  it("ships no placeholder text", () => {
    const { container } = render(<BrandLanding />);
    expect(container.textContent).not.toMatch(/\[[^\]]+\]/);
    expect(container.textContent).not.toMatch(/lorem|TODO|FİYAT/i);
  });

  it("answers the FAQ with native disclosure, three questions", () => {
    const { container } = render(<BrandLanding />);
    expect(container.querySelectorAll("details")).toHaveLength(3);
  });
});

describe("Brand landing: product tabs", () => {
  it("selects the first tab and points each tab at the one panel it controls", () => {
    render(<BrandLanding />);
    const tablist = screen.getByRole("tablist", { name: m.product.tablistLabel });
    const list = within(tablist).getAllByRole("tab");
    expect(list).toHaveLength(tabOrder.length);
    expect(list[0]).toHaveAttribute("aria-selected", "true");
    expect(list[0]).toHaveAttribute("tabindex", "0");
    list.slice(1).forEach((t) => {
      expect(t).toHaveAttribute("aria-selected", "false");
      expect(t).toHaveAttribute("tabindex", "-1");
    });
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("id", list[0].getAttribute("aria-controls"));
    expect(panel).toHaveAttribute("aria-labelledby", list[0].id);
  });

  it("moves selection and focus with the arrow, Home and End keys", async () => {
    const user = userEvent.setup();
    render(<BrandLanding />);
    const list = screen.getAllByRole("tab");

    list[0].focus();
    await user.keyboard("{ArrowRight}");
    expect(list[1]).toHaveAttribute("aria-selected", "true");
    expect(list[1]).toHaveFocus();
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", list[1].id);

    await user.keyboard("{End}");
    expect(list[3]).toHaveAttribute("aria-selected", "true");
    expect(list[3]).toHaveFocus();

    await user.keyboard("{ArrowRight}"); // wraps to the first
    expect(list[0]).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{ArrowLeft}"); // wraps to the last
    expect(list[3]).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{Home}");
    expect(list[0]).toHaveAttribute("aria-selected", "true");
  });

  it("changes the panel on click", async () => {
    const user = userEvent.setup();
    render(<BrandLanding />);
    await user.click(screen.getByRole("tab", { name: /Onay/ }));
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Gelen havale ₺42.800");
    await user.click(screen.getByRole("tab", { name: /Rapor/ }));
    expect(screen.getByRole("tabpanel")).toHaveTextContent("2026-46");
  });
});

describe("Brand landing: sample figures", () => {
  it("formats Turkish money with a real minus and the symbol first", () => {
    expect(formatTry(-184.2)).toBe("−₺184.200");
    expect(formatTry(612.4)).toBe("₺612.400");
    expect(formatTry(-34.2)).toBe("−₺34.200");
  });

  it("agrees with the route: opening 612.400, lowest in week 6, closing −34.200", () => {
    expect(sampleClose[0]).toBe(612.4);
    expect(sampleClose[6]).toBe(-184.2);
    expect(Math.min(...sampleClose)).toBe(sampleClose[6]);
    expect(sampleClose[13]).toBe(-34.2);
    expect(sampleClose).toHaveLength(14);
  });

  it("states the lowest week once, the same way, on the answer panel", () => {
    render(<BrandLanding />);
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveTextContent("6. haftada");
    expect(panel).toHaveTextContent("₺184.200 açık veriyor");
    expect(panel).toHaveTextContent("−₺184.200");
  });

  it("keeps the curve inside its box, with the lowest week deepest", () => {
    const ys = sampleClose.map((v, i) => curvePoint(i, v).y);
    expect(Math.min(...ys)).toBeGreaterThanOrEqual(-4);
    expect(Math.max(...ys)).toBeLessThanOrEqual(310);
    expect(ys.indexOf(Math.max(...ys))).toBe(6);
  });
});

describe("Storm scene maths", () => {
  it("is deterministic for the same time and changes over time", () => {
    expect(frame(2).sail).toBe(frame(2).sail);
    expect(frame(2).ship).not.toBe(frame(3.2).ship);
    expect(frame(2).w2).not.toBe(frame(4).w2);
  });

  it("puts the keel on the wave it sails on", () => {
    for (const t of [2, 5.5, 9.1]) {
      const f = frame(t);
      expect(Number.isFinite(f.shipY)).toBe(true);
      expect(Number.isFinite(f.shipAngle)).toBe(true);
      expect(Math.abs(f.shipAngle)).toBeLessThan(25);
    }
    expect(waveAt({ base: 100, c: [[10, 0.01, 1, 0]] }, 0, 0).y).toBe(100);
  });

  it("flashes twice then fades, and the bolt runs from the sky down", () => {
    expect(flashLevel(-1)).toBe(0);
    expect(flashLevel(0.05)).toBe(1);
    expect(flashLevel(0.1)).toBeLessThan(0.2);
    expect(flashLevel(0.18)).toBeGreaterThan(0.8);
    expect(flashLevel(1)).toBe(0);

    let seed = 7;
    const rand = () => {
      seed = (seed * 16807) % 2147483647;
      return seed / 2147483647;
    };
    const pts = lightningBolt(rand).split(" ").map((p) => p.split(",").map(Number));
    expect(pts[0][1]).toBe(0);
    expect(pts[pts.length - 1][1]).toBeGreaterThanOrEqual(230);
  });
});
