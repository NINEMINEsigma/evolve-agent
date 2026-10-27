import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFile } from "node:fs/promises";
import { createSourceBridge, iconPath, previewRoot, sourceRoot } from "./build/sourceBridge";
import { securityPolicy } from "./build/securityPolicy";

let building = false;

export default defineConfig({
  root: previewRoot,
  base: "/",
  plugins: [
    createSourceBridge(), react(),
    {
      name: "preview-document-policy",
      configResolved(config) { building = config.command === "build"; },
      transformIndexHtml: {
        order: "pre",
        handler: (html) => html.replace("__PREVIEW_CSP__", securityPolicy()),
      },
      configureServer(server) {
        server.middlewares.use("/icon.ico", async (_request, response, next) => {
          try { response.setHeader("Content-Type", "image/x-icon"); response.end(await readFile(iconPath)); }
          catch (error) { next(error); }
        });
      },
      async buildStart() {
        if (building) this.emitFile({ type: "asset", fileName: "icon.ico", source: await readFile(iconPath) });
      },
    },
  ],
  resolve: { dedupe: ["react", "react-dom", "zustand"] },
  server: {
    host: "127.0.0.1", port: 4178, strictPort: true, hmr: false,
    fs: { strict: true, allow: [previewRoot, sourceRoot, iconPath] },
    headers: { "Content-Security-Policy": securityPolicy() },
  },
  preview: {
    host: "127.0.0.1", port: 4179, strictPort: true,
    headers: { "Content-Security-Policy": securityPolicy() },
  },
  worker: { plugins: () => [createSourceBridge()] },
  build: { outDir: "dist", emptyOutDir: true, assetsDir: "assets" },
});
