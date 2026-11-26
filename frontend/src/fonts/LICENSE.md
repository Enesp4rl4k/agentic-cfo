# Self-hosted brand fonts

The woff2 files in this directory are the latin and latin-ext subsets of four families,
as served by Google Fonts and unmodified. Each family is licensed under the SIL Open Font
License, Version 1.1; the complete licence text, with the family's copyright notice and
Reserved Font Name statement, sits next to the files and travels with them:

| Family | Files | Notice and licence text |
|---|---|---|
| Cinzel | `cinzel-*.woff2` | `OFL-cinzel.txt` |
| Cormorant Garamond | `cormorant-garamond-*.woff2` | `OFL-cormorant-garamond.txt` |
| IBM Plex Sans | `ibm-plex-sans-*.woff2` | `OFL-ibm-plex-sans.txt` |
| IBM Plex Mono | `ibm-plex-mono-*.woff2` | `OFL-ibm-plex-mono.txt` |

The OFL files are copied verbatim from each family's `OFL.txt` in the Google Fonts
repository (github.com/google/fonts, `ofl/<family>/OFL.txt`), the distribution these
files come from. Do not edit them; do not sell the fonts on their own.

Why they are committed: `next/font/google` downloaded them on every `next build`, and a
network failure there failed CI. See `src/lib/brand-fonts.ts`.
