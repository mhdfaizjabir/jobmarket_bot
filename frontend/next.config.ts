import type { NextConfig } from "next";

// Security headers for the frontend origin (Sprint 5).
//
// Intentionally NO blocking Content-Security-Policy yet: the app relies heavily
// on inline `style={}` attributes and Recharts' injected styles, so a strict
// `style-src` would break rendering. Adding CSP correctly needs it tuned in
// Report-Only mode against the live rendered app first — tracked in SECURITY.md
// as the one deferred frontend item. Everything below is safe to apply blindly.
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
];

const nextConfig: NextConfig = {
  output: "standalone", // minimal self-contained server for the Docker image
  poweredByHeader: false, // don't advertise the framework (removes X-Powered-By)
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
