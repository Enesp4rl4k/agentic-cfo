/**
 * Landing page layout — no auth required, no sidebar.
 * Served at / for unauthenticated visitors.
 */
export default function LandingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
