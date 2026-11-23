import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// In development the API runs on :8000; Vite proxies /api so cookies stay same-origin,
// exactly as Nginx does in production.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: false } },
  },
  build: {
    sourcemap: false,
    outDir: "dist",
    rollupOptions: {
      output: {
        // Libraries change rarely: keeping them in their own file lets browsers reuse it after an upgrade.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom)[\\/]/.test(id)) return "react";
          if (id.includes("@tanstack") || id.includes("i18next")) return "libs";
          if (id.includes("lucide-react")) return "icons";
          return undefined;
        },
      },
    },
  },
  test: { environment: "node", setupFiles: ["src/test/setup.ts"] },
});
