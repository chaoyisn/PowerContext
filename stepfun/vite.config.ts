import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  root: "frontend",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:4174" },
  },
  worker: { format: "es" },
  build: { outDir: "dist", emptyOutDir: true, copyPublicDir: false },
});
