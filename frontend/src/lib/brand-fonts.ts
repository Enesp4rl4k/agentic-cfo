import { Cinzel, Cormorant_Garamond, IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";

/**
 * The brand's four faces, shared by the landing and the branded app pages.
 * Scoped as `--tc-font-*` variables so the app's Inter stays untouched everywhere
 * else. `latin-ext` is required: Turkish İ ı Ş ş Ğ ğ live there.
 */
const cinzel = Cinzel({ subsets: ["latin", "latin-ext"], display: "swap", variable: "--tc-font-cinzel" });
const display = Cormorant_Garamond({
  subsets: ["latin", "latin-ext"],
  weight: ["500", "600", "700"],
  style: ["normal", "italic"],
  display: "swap",
  variable: "--tc-font-display",
});
const body = IBM_Plex_Sans({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "600"],
  display: "swap",
  variable: "--tc-font-body",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500"],
  display: "swap",
  variable: "--tc-font-mono",
});

export const brandFontVars = `${cinzel.variable} ${display.variable} ${body.variable} ${mono.variable}`;
