# Self-hosted brand fonts

The woff2 files in this directory are the latin and latin-ext subsets of four families,
as served by Google Fonts and unmodified:

| Family | Files | Copyright | Licence |
|---|---|---|---|
| Cinzel | `cinzel-*.woff2` | The Cinzel Project Authors (https://github.com/NDISCOVER/Cinzel) | SIL OFL 1.1 |
| Cormorant Garamond | `cormorant-garamond-*.woff2` | The Cormorant Project Authors (https://github.com/CatharsisFonts/Cormorant) | SIL OFL 1.1 |
| IBM Plex Sans | `ibm-plex-sans-*.woff2` | IBM Corp. (https://github.com/IBM/plex) | SIL OFL 1.1 |
| IBM Plex Mono | `ibm-plex-mono-*.woff2` | IBM Corp. (https://github.com/IBM/plex) | SIL OFL 1.1 |

The SIL Open Font License, Version 1.1, permits using, embedding and redistributing
these fonts with software, provided the copyright notice and licence travel with them
and the fonts are not sold on their own: https://openfontlicense.org/open-font-license-official-text/

Why they are committed: `next/font/google` downloaded them on every `next build`, and a
network failure there failed CI. See `src/lib/brand-fonts.ts`.
