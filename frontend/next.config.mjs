/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // This is a fully client-side dashboard app — all pages use useSearchParams
  // and must be rendered dynamically (no static prerendering).
  experimental: {
    missingSuspenseWithCSRBailout: false,
  },
};

export default nextConfig;
