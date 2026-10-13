// Gives the service worker's cache the build id, so a new build replaces the old shell
// (and its hashed chunks) instead of piling up next to it
import { readFileSync, writeFileSync } from "node:fs";

const buildId = readFileSync(".next/BUILD_ID", "utf8").trim();
const path = "out/sw.js";
const source = readFileSync(path, "utf8");
if (!source.includes("__BUILD_ID__")) throw new Error(`${path}: no __BUILD_ID__ placeholder`);
writeFileSync(path, source.replaceAll("__BUILD_ID__", buildId));
console.log(`sw.js: cache avaris-shell-${buildId}`);
