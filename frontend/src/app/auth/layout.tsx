/**
 * Auth pages layout — minimal, no sidebar, centered content.
 * Used for /auth/login and /auth/register.
 */
export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-background">
      {children}
    </div>
  );
}
