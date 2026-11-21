/**
 * A failed action, in words. A 403 is the server saying the role may not do
 * this (stale browser role, role changed meanwhile): its own sentence names
 * what was needed and is shown as given, else the role gate's generic one.
 * Anything else falls back to the caller's message.
 */
export function isForbidden(e: unknown): boolean {
  return (e as { status?: number } | null)?.status === 403;
}

export function failureMessage(e: unknown, fallback: string, forbidden: string): string {
  if (isForbidden(e)) {
    const detail = e instanceof Error ? e.message : "";
    return detail || forbidden;
  }
  return fallback;
}
