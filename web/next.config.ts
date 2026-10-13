import type { NextConfig } from "next";

// Static export: FastAPI serves web/out, there is no Node server at runtime
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  // A warm build cache once shipped the previous build's CSS; builds are rare and small
  experimental: { turbopackFileSystemCacheForBuild: false },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
