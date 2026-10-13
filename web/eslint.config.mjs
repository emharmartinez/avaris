import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "test-results/**",
    "playwright-report/**",
  ]),
  {
    // The service worker is a classic script with browser worker globals
    files: ["public/sw.js"],
    languageOptions: { globals: { self: "readonly", caches: "readonly", fetch: "readonly" } },
  },
]);

export default eslintConfig;
