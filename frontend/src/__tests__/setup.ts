/**
 * Vitest global setup — runs before every test file.
 */
import "@testing-library/jest-dom";
import { vi, beforeAll, afterAll, beforeEach } from "vitest";

// ── One clock ──────────────────────────────────────────────────────────────────
// Every test starts at the instant the backend suite is pinned to (backend/app/core/clock.py TEST_INSTANT, a
// Wednesday 10:00 UTC) and Date ticks from there. Only Date moves: timers stay real, and a test's own
// vi.useFakeTimers() starts from this instant too (it reads Date.now()). A test that truly needs the wall
// clock says so: vi.useFakeTimers({ toFake: ["Date"], now: performance.timeOrigin + performance.now() }).
// Guarded by backend/tests/test_clock_guard.py.
const TEST_INSTANT = "2026-11-25T10:00:00Z";
const WallDate = Date;
let offsetMs = WallDate.parse(TEST_INSTANT) - WallDate.now(); // module-level code sees the instant too
class PinnedDate extends WallDate {
  constructor(...args: unknown[]) {
    if (args.length === 0) super(WallDate.now() + offsetMs);
    else super(...(args as [number]));
  }
  static now(): number {
    return WallDate.now() + offsetMs;
  }
}
globalThis.Date = PinnedDate as DateConstructor;
beforeEach(() => {
  offsetMs = WallDate.parse(TEST_INSTANT) - WallDate.now();
});

// ── Mock next/navigation ───────────────────────────────────────────────────────
vi.mock("next/navigation", () => ({
  useRouter:       () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => ({ get: vi.fn().mockReturnValue(null) }),
  usePathname:     () => "/",
}));

// ── Mock next/font/google ──────────────────────────────────────────────────────
// The font loaders are compiled away by Next's own plugin; under vitest they are not
// functions. Every face resolves to an empty class and variable name.
vi.mock("next/font/google", () => {
  const face = () => ({ className: "", variable: "", style: {} });
  return {
    Inter: face,
    Cinzel: face,
    Cormorant_Garamond: face,
    IBM_Plex_Mono: face,
    IBM_Plex_Sans: face,
  };
});

// ── Mock next/font/local ───────────────────────────────────────────────────────
// The brand faces are self-hosted (lib/brand-fonts.ts); like the Google loaders they are compiled away.
vi.mock("next/font/local", () => ({
  default: () => ({ className: "", variable: "", style: {} }),
}));

// ── Mock next-auth/react ───────────────────────────────────────────────────────
vi.mock("next-auth/react", () => ({
  signIn:     vi.fn(),
  signOut:    vi.fn(),
  // Default: an established session (apiClient + startGuestDemo post-check).
  // Tests override with mockResolvedValueOnce to simulate the csrf race where
  // signIn reports success but no session cookie exists.
  getSession: vi.fn().mockResolvedValue({ accessToken: "tok" }),
  useSession: vi.fn().mockReturnValue({
    data:   { user: { id: "1", email: "test@example.com", role: "admin", orgId: "org1" }, accessToken: "tok" },
    status: "authenticated",
  }),
  SessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

// ── Mock lucide-react (avoids SVG parse issues in jsdom) ─────────────────────
vi.mock("lucide-react", () =>
  new Proxy(
    {},
    {
      get: (_target, prop) => {
        // A module whose `then` is a function is awaited as a promise, and a
        // component never resolves: any page using an icon hung on import.
        if (prop === "then") return undefined;
        // Return a no-op component for every named export
        const MockIcon = () => null;
        MockIcon.displayName = String(prop);
        return MockIcon;
      },
      // Vitest asks the mock whether an export exists before reading it; an
      // empty target said no to every icon, so no rendered page could use one.
      has: (_target, prop) => prop !== "then",
    }
  )
);

// ── Mock next/image ────────────────────────────────────────────────────────────
vi.mock("next/image", () => ({
  default: ({ src, alt }: { src: string; alt: string }) => {
    // eslint-disable-next-line @next/next/no-img-element
    return null; // jsdom doesn't load images
  },
}));

// ── Mock IntersectionObserver for JSDOM ───────────────────────────────────────
class MockIntersectionObserver {
  callback: (entries: Array<{ isIntersecting: boolean; target: Element }>) => void;
  constructor(callback: (entries: Array<{ isIntersecting: boolean; target: Element }>) => void) {
    this.callback = callback;
  }
  observe = vi.fn((el: Element) => {
    if (this.callback) {
      this.callback([{ isIntersecting: true, target: el }]);
    }
  });
  unobserve = vi.fn();
  disconnect = vi.fn();
}
Object.defineProperty(globalThis, "IntersectionObserver", {
  writable: true,
  configurable: true,
  value: MockIntersectionObserver,
});

// ── Suppress console.error noise in tests ─────────────────────────────────────
const originalError = console.error;
beforeAll(() => {
  console.error = (...args: unknown[]) => {
    const msg = String(args[0] ?? "");
    // Suppress known React act() warnings in test environment
    if (msg.includes("Warning:") || msg.includes("act(")) return;
    originalError(...args);
  };
});
afterAll(() => {
  console.error = originalError;
});
