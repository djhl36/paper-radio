import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 배포 위치: <repo>/docs/energy  → GitHub Pages에서 /paper-radio/energy/ 로 서빙
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../../docs/energy",
    emptyOutDir: true
  },
  server: { host: true, port: 5178 }
});
