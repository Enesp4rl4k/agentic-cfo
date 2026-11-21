/**
 * Who may open which screen — the browser's copy of the backend's role classes.
 *
 * One map, mirrored from `backend/app/api/access.py` (`WRITER_ROLES`,
 * `DECIDER_ROLES`, `CONTRIBUTOR_ROLES`) and checked against it by
 * `src/__tests__/roles.test.ts`, so the two cannot drift apart. The middleware
 * only hides pages; the backend is the authority and answers 403 on its own.
 *
 *   contributor  brings data in and runs analyses: owner, admin, cfo, smmm, analyst
 *   writer       changes the books: owner, admin, cfo, smmm
 *   decider      decides: owner, admin
 *   billing      pays and manages the plan: owner, admin, cfo (billing.py)
 *
 * `viewer` is in none of them; an unknown role is in none of them.
 */

export type RoleClass = "contributor" | "writer" | "decider" | "billing";

export const ROLE_CLASSES: Record<RoleClass, readonly string[]> = {
  contributor: ["owner", "admin", "cfo", "smmm", "analyst"],
  writer: ["owner", "admin", "cfo", "smmm"],
  decider: ["owner", "admin"],
  billing: ["owner", "admin", "cfo"],
};

export function hasRoleClass(role: string | null | undefined, cls: RoleClass): boolean {
  return !!role && ROLE_CLASSES[cls].includes(role);
}

/** Path prefix -> the class that may open it. First match wins. */
export const ROUTE_RULES: ReadonlyArray<{ prefix: string; cls: RoleClass }> = [
  // Workspace settings: members and invitations are the owner's and admin's.
  { prefix: "/settings/workspace", cls: "decider" },
  // Alert preferences are written by whoever may change working data.
  { prefix: "/settings/alerts", cls: "writer" },
  { prefix: "/settings/billing", cls: "billing" },
  // Upload is bringing data in: an analyst may (Organization: "can upload, run
  // analysis"), and so may cfo and smmm, which the old ranking left out.
  { prefix: "/upload", cls: "contributor" },
  // Pilot administration is the platform operator's; the page cannot know who
  // that is (an allow-list on the server), so it is hidden from everyone who
  // is not at least a decider and the server refuses the rest.
  { prefix: "/pilot", cls: "decider" },
];
