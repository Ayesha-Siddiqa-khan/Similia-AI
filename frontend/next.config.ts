import type { NextConfig } from "next";

// Browser security headers. The microphone is allowed for this site only (voice typing); camera,
// location and payment are switched off. HSTS is sent in production only, because it must not
// be pinned for plain-http localhost.
// Content-Security-Policy: scripts, styles, images and fonts only from this site. The browser may
// call this site and the Supabase project (sign-in); nothing else. Next.js needs inline scripts
// for hydration, so script-src keeps 'unsafe-inline' (a nonce policy would disable static pages);
// 'unsafe-eval' and websockets are added in development only (hot reload).
const dev = process.env.NODE_ENV !== "production";
// The desktop shell serves the app over loopback HTTP. HSTS and
// upgrade-insecure-requests would break asset loading there, so they are
// omitted in desktop mode only.
const desktop = process.env.SIMILIA_DESKTOP === "1";
const supabaseOrigin = (() => {
  try { return new URL(process.env.NEXT_PUBLIC_SUPABASE_URL ?? "").origin; } catch { return ""; }
})();
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self' ${supabaseOrigin}${dev ? " ws: wss:" : ""}`.trim(),
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  ...(dev || desktop ? [] : ["upgrade-insecure-requests"]),
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "microphone=(self), camera=(), geolocation=(), payment=()" },
  ...(process.env.NODE_ENV === "production" && !desktop
    ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" }]
    : []),
];

const nextConfig: NextConfig = {
  /* config options here */
  poweredByHeader: false,
  // The desktop build runs Next's own production server from the standalone
  // output; it includes every runtime dependency the server needs.
  output: "standalone",
  ...(desktop ? { outputFileTracingRoot: process.cwd() } : {}),
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  experimental: {
    // Book uploads go through the proxy; the default 10 MB buffer cut them off (the app allows 50 MB).
    proxyClientMaxBodySize: "55mb",
    agentUpgrade: "security",
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    ...(desktop ? { root: process.cwd() } : {}),
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
