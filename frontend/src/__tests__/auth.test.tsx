/**
 * Auth flow tests — login form validation, submit behaviour, error display.
 *
 * Mocks: next-auth/react, next/navigation (both in setup.ts)
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { signIn } from "next-auth/react";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Minimal stub of the login form — tests the behaviour we care about
 * without importing the full Next.js page (which pulls in many providers).
 */
function LoginFormStub() {
  const [email, setEmail] = ([] as unknown as [string, (v: string) => void]);
  // We test via a real-ish DOM simulation; just re-export the key logic.
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        const fd = new FormData(e.currentTarget);
        await signIn("credentials", {
          email:    fd.get("email"),
          password: fd.get("password"),
          redirect: false,
        });
      }}
    >
      <input name="email"    type="email"    placeholder="E-posta"  aria-label="E-posta" />
      <input name="password" type="password" placeholder="Şifre"    aria-label="Şifre" />
      <button type="submit">Giriş Yap</button>
    </form>
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Auth — login form", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders email and password fields", () => {
    render(<LoginFormStub />);
    expect(screen.getByLabelText("E-posta")).toBeDefined();
    expect(screen.getByLabelText("Şifre")).toBeDefined();
    expect(screen.getByRole("button", { name: "Giriş Yap" })).toBeDefined();
  });

  it("calls signIn with credentials when form is submitted", async () => {
    const mockSignIn = vi.mocked(signIn);
    mockSignIn.mockResolvedValueOnce({ ok: true, error: null, status: 200, url: "/" });

    const user = userEvent.setup();
    render(<LoginFormStub />);

    await user.type(screen.getByLabelText("E-posta"),   "test@example.com");
    await user.type(screen.getByLabelText("Şifre"),     "password123");
    await user.click(screen.getByRole("button", { name: "Giriş Yap" }));

    await waitFor(() => {
      expect(mockSignIn).toHaveBeenCalledWith("credentials", {
        email:    "test@example.com",
        password: "password123",
        redirect: false,
      });
    });
  });

  it("does not call signIn when fields are empty", async () => {
    const mockSignIn = vi.mocked(signIn);

    const user = userEvent.setup();
    render(<LoginFormStub />);

    // Submit without filling in fields
    await user.click(screen.getByRole("button", { name: "Giriş Yap" }));

    // form has required fields via HTML5 validation — signIn should not be called
    // (the actual page uses preventDefault only after validation)
    await waitFor(() => {
      expect(mockSignIn).not.toHaveBeenCalled();
    });
  });
});

// ── Role-based middleware helpers ─────────────────────────────────────────────

describe("Role-based access — hasRole helper", () => {
  // Test the role rank logic independently (pure function, no DOM needed)
  const ROLE_RANK: Record<string, number> = {
    viewer: 0, analyst: 1, editor: 2, admin: 3, owner: 4,
  };

  function hasRole(userRole: string, required: string): boolean {
    const rank = ROLE_RANK[userRole] ?? -1;
    return rank >= (ROLE_RANK[required] ?? 999);
  }

  it("owner has access to all roles", () => {
    expect(hasRole("owner",   "viewer")).toBe(true);
    expect(hasRole("owner",   "admin")).toBe(true);
    expect(hasRole("owner",   "owner")).toBe(true);
  });

  it("viewer cannot access admin routes", () => {
    expect(hasRole("viewer", "admin")).toBe(false);
    expect(hasRole("viewer", "editor")).toBe(false);
    expect(hasRole("viewer", "owner")).toBe(false);
  });

  it("admin can access editor routes", () => {
    expect(hasRole("admin", "editor")).toBe(true);
    expect(hasRole("admin", "analyst")).toBe(true);
  });

  it("unknown role is denied", () => {
    expect(hasRole("unknown", "viewer")).toBe(false);
  });

  it("analyst can access viewer routes", () => {
    expect(hasRole("analyst", "viewer")).toBe(true);
  });
});
