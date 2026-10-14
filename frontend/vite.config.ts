/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev only: the built UI is served by FastAPI itself (docs/DECISIONS.md D1).
const apiTarget = process.env.API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Analyses take up to ~2 minutes; keep the proxy from cutting them off.
      "/api": { target: apiTarget, timeout: 300_000, proxyTimeout: 300_000 },
      "/health": apiTarget,
    },
  },
  test: {
    environment: "jsdom",
  },
});
