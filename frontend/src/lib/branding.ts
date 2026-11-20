/**
 * Product identity, in one place.
 *
 * The name, domain and social handles used to be typed straight into the navbar,
 * the footer, the pricing table and the landing hero. Renaming the product meant
 * a grep across the tree — and the mailto: links pointed at a domain the project
 * does not own.
 *
 * Everything user-visible resolves through here. Contact links are omitted
 * entirely when no domain is configured, rather than rendering an address that
 * bounces.
 *
 * Mirrors `backend/app/core/branding.py`. Both default to no domain on purpose.
 */

/**
 * Each variable is read by its full name, never through a computed key: Next inlines
 * `NEXT_PUBLIC_*` into the browser bundle only for static references. A dynamic read made the
 * override work on the server and fall back to the default in the browser, so the name changed
 * in the page title but not in the logo, and the two disagreed at hydration.
 */
const clean = (value: string | undefined): string => (value ?? "").trim();

const NAME = clean(process.env.NEXT_PUBLIC_BRAND_NAME) || "Tiphys";
const DOMAIN = clean(process.env.NEXT_PUBLIC_BRAND_DOMAIN).toLowerCase();

const address = (local: string): string | null =>
  DOMAIN ? `${local}@${DOMAIN}` : null;

export const brand = {
  name: NAME,
  domain: DOMAIN,
  /** False when no domain is set — callers must not render a contact link. */
  hasDomain: Boolean(DOMAIN),
  legalName: `${NAME} Platform`,
  appUrl: clean(process.env.NEXT_PUBLIC_BRAND_APP_URL) || null,
  contactEmail: clean(process.env.NEXT_PUBLIC_BRAND_CONTACT_EMAIL) || address("hello"),
  twitterUrl: clean(process.env.NEXT_PUBLIC_BRAND_TWITTER_URL) || null,
  linkedinUrl: clean(process.env.NEXT_PUBLIC_BRAND_LINKEDIN_URL) || null,
} as const;

/** `mailto:` href, or null when there is no address to link to. */
export const contactHref = (): string | null =>
  brand.contactEmail ? `mailto:${brand.contactEmail}` : null;

/**
 * Prefix for browser-storage keys.
 *
 * Deliberately *not* derived from the brand name: these keys are already
 * written in users' browsers, and renaming the product must not silently
 * discard their dismissed banners and completed tours.
 */
export const STORAGE_PREFIX = "clevelai" as const;
