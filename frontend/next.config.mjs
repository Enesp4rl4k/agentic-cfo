/** @type {import('next').NextConfig} */

// Bundle analyzer — run: ANALYZE=true npm run build
// Then open .next/analyze/client.html
const withBundleAnalyzer = process.env.ANALYZE === "true"
  ? (await import("@next/bundle-analyzer").then((m) => m.default({ enabled: true })))
  : (cfg) => cfg;

const nextConfig = {
  output: "standalone",

  // This is a fully client-side dashboard app — all pages use useSearchParams
  // and must be rendered dynamically (no static prerendering).
  experimental: {
    missingSuspenseWithCSRBailout: false,
  },

  // ── Performance: compiler optimizations ────────────────────────────────────
  compiler: {
    // Remove console.log in production builds
    removeConsole: process.env.NODE_ENV === "production"
      ? { exclude: ["error", "warn"] }
      : false,
  },

  // ── Security Headers ───────────────────────────────────────────────────────
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-XSS-Protection", value: "1; mode=block" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },

  // ── Webpack: split large vendor chunks ─────────────────────────────────────
  webpack(config, { isServer }) {
    if (!isServer) {
      config.optimization.splitChunks = {
        ...config.optimization.splitChunks,
        cacheGroups: {
          // Recharts is large (~500KB) — isolate in its own chunk
          recharts: {
            test: /[\\/]node_modules[\\/]recharts[\\/]/,
            name: "recharts",
            chunks: "all",
            priority: 30,
          },
          // Radix UI primitives — shared across many components
          radix: {
            test: /[\\/]node_modules[\\/]@radix-ui[\\/]/,
            name: "radix",
            chunks: "all",
            priority: 20,
          },
          // lucide-react icon library — tree-shaken per import but still large
          lucide: {
            test: /[\\/]node_modules[\\/]lucide-react[\\/]/,
            name: "lucide",
            chunks: "all",
            priority: 15,
          },
        },
      };
    }
    return config;
  },
};

export default withBundleAnalyzer(nextConfig);
