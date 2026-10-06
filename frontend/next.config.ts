import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Bottom-left would cover the navigation rail's sign-out button in development.
  devIndicators: { position: "bottom-right" },
};

export default nextConfig;
