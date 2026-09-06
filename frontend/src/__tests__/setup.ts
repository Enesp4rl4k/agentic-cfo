/**
 * Vitest global setup — runs before every test file.
 */
import "@testing-library/jest-dom";
import { vi, beforeAll, afterAll } from "vitest";

// ── Mock next/navigation ───────────────────────────────────────────────────────
vi.mock("next/navigation", () => ({
  useRouter:       () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => ({ get: vi.fn().mockReturnValue(null) }),
  usePathname:     () => "/",
}));

// ── Mock next-auth/react ───────────────────────────────────────────────────────
vi.mock("next-auth/react", () => ({
  signIn:     vi.fn(),
  signOut:    vi.fn(),
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
        // Return a no-op component for every named export
        const MockIcon = () => null;
        MockIcon.displayName = String(prop);
        return MockIcon;
      },
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
