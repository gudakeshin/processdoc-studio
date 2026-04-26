/** @type {import('next').NextConfig} */
const apiTarget = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";

const nextConfig = {
  experimental: {
    // Backend LLM calls can exceed the default ~30s proxy timeout. Allow up to 2 minutes.
    proxyTimeout: 120000,
  },
  // When the browser uses same-origin `/api/*` (NEXT_PUBLIC_API_URL=same-origin), forward to FastAPI.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiTarget.replace(/\/$/, "")}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
