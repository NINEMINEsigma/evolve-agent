import react from "@vitejs/plugin-react";
import path from "node:path";
import {defineConfig} from "vite";

export default defineConfig({
  root: __dirname,
  base: "./",
  publicDir: path.resolve(__dirname, "../public"),
  plugins: [react()],
  server: {port: Number(process.env.PROMO_WEB_PORT || 0), strictPort: false, host: process.env.PROMO_WEB_HOST || "127.0.0.1"},
  build: {outDir: path.resolve(__dirname, "../out/web"), emptyOutDir: true},
});
