import localFont from "next/font/local";

/**
 * The brand's four faces, shared by the landing and the branded app pages.
 * `--tc-font-*` (see globals.css) stay scoped to the brand so the app's Inter is untouched
 * everywhere else. `latin-ext` is required: Turkish İ ı Ş ş Ğ ğ live there.
 *
 * Self-hosted (src/fonts/, SIL Open Font License 1.1, see src/fonts/LICENSE.md) instead of
 * `next/font/google`: that fetched the faces from fonts.googleapis.com on every `next build`,
 * so a network blip failed the build (Pilot flow, Frontend CI, the Docker image) for no
 * reason in the code. The files are Google Fonts' own latin and latin-ext woff2 subsets,
 * byte for byte what the build used to download, so the rendered type is unchanged.
 *
 * Each family is two sets split by the same unicode-range Google serves. The font loaders
 * only accept literal options, so each set sets its own `--tcf-*` variable and globals.css
 * joins them into the `--tc-font-*` list (latin-ext first, then latin: a character is drawn
 * from whichever file covers it). The latin-ext sets turn the metric fallback off: it would
 * sit between the two files and claim every latin character.
 */
const cinzelLatin = localFont({
  src: [
    { path: "../fonts/cinzel-latin.woff2", weight: "400 900", style: "normal" },
  ],
  display: "swap",
  variable: "--tcf-cinzel-latin",
  declarations: [{ prop: "unicode-range", value: "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD" }],
});

const cinzelExt = localFont({
  src: [
    { path: "../fonts/cinzel-latin-ext.woff2", weight: "400 900", style: "normal" },
  ],
  display: "swap",
  variable: "--tcf-cinzel-latin-ext",
  declarations: [{ prop: "unicode-range", value: "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C4, U+2113, U+2C60-2C7F, U+A720-A7FF" }],
  adjustFontFallback: false,
});

const displayLatin = localFont({
  src: [
    { path: "../fonts/cormorant-garamond-latin-normal.woff2", weight: "500 700", style: "normal" },
    { path: "../fonts/cormorant-garamond-latin-italic.woff2", weight: "500 700", style: "italic" },
  ],
  display: "swap",
  variable: "--tcf-cormorant-latin",
  declarations: [{ prop: "unicode-range", value: "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD" }],
});

const displayExt = localFont({
  src: [
    { path: "../fonts/cormorant-garamond-latin-ext-normal.woff2", weight: "500 700", style: "normal" },
    { path: "../fonts/cormorant-garamond-latin-ext-italic.woff2", weight: "500 700", style: "italic" },
  ],
  display: "swap",
  variable: "--tcf-cormorant-latin-ext",
  declarations: [{ prop: "unicode-range", value: "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C4, U+2113, U+2C60-2C7F, U+A720-A7FF" }],
  adjustFontFallback: false,
});

const bodyLatin = localFont({
  src: [
    { path: "../fonts/ibm-plex-sans-latin-normal.woff2", weight: "400 600", style: "normal" },
  ],
  display: "swap",
  variable: "--tcf-plex-sans-latin",
  declarations: [{ prop: "unicode-range", value: "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD" }],
});

const bodyExt = localFont({
  src: [
    { path: "../fonts/ibm-plex-sans-latin-ext-normal.woff2", weight: "400 600", style: "normal" },
  ],
  display: "swap",
  variable: "--tcf-plex-sans-latin-ext",
  declarations: [{ prop: "unicode-range", value: "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C4, U+2113, U+2C60-2C7F, U+A720-A7FF" }],
  adjustFontFallback: false,
});

const monoLatin = localFont({
  src: [
    { path: "../fonts/ibm-plex-mono-latin-normal-400.woff2", weight: "400", style: "normal" },
    { path: "../fonts/ibm-plex-mono-latin-normal-500.woff2", weight: "500", style: "normal" },
  ],
  display: "swap",
  variable: "--tcf-plex-mono-latin",
  declarations: [{ prop: "unicode-range", value: "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD" }],
});

const monoExt = localFont({
  src: [
    { path: "../fonts/ibm-plex-mono-latin-ext-normal-400.woff2", weight: "400", style: "normal" },
    { path: "../fonts/ibm-plex-mono-latin-ext-normal-500.woff2", weight: "500", style: "normal" },
  ],
  display: "swap",
  variable: "--tcf-plex-mono-latin-ext",
  declarations: [{ prop: "unicode-range", value: "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C4, U+2113, U+2C60-2C7F, U+A720-A7FF" }],
  adjustFontFallback: false,
});

export const brandFontVars = [
  cinzelLatin.variable,
  cinzelExt.variable,
  displayLatin.variable,
  displayExt.variable,
  bodyLatin.variable,
  bodyExt.variable,
  monoLatin.variable,
  monoExt.variable,
].join(" ");
