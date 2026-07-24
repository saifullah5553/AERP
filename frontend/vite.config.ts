import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";

// In dev, proxy /api to the FastAPI backend so the browser makes same-origin
// requests (no CORS) and no API base URL needs to be configured.
export default defineConfig({
  // VITE_BASE lets the GitHub Pages build serve from the /AERP/ subpath.
  base: process.env.VITE_BASE || "/",
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: { outDir: "dist", sourcemap: true },
});
