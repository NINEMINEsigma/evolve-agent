/**
 * 离线阅读器独立构建配置。
 *
 * 产物为单个 IIFE JS（dist/export/viewer.js）与单个 CSS（dist/export/viewer.css），
 * 由后端固定只读路由 GET /api/session-export/viewer/{asset_name} 提供，嵌入自包含
 * 的导出 index.html。inlineDynamicImports 禁止额外网络 chunk；KaTeX 字体与内置 CSS
 * 图片通过 data URL 内联，保证 file:// 双击离线打开时不依赖任何外部请求。
 *
 * 不设置 base、不复制应用 dist、不依赖 ESM 入口。入口为相对 root 的路径。
 */

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // 依赖中仍可能存在 Node 风格的 process.env 访问；离线 viewer 运行在浏览器中，
  // 构建时将其固定为生产环境，避免生成的 IIFE 依赖 Node 全局对象。
  define: {
    process: JSON.stringify({ env: { NODE_ENV: "production" } }),
  },
  build: {
    outDir: "dist/export",
    emptyOutDir: false,
    cssCodeSplit: false,
    assetsInlineLimit: 100 * 1024 * 1024,
    lib: {
      entry: "src/features/sessionExport/offline/main.tsx",
      name: "OfflineViewer",
      formats: ["iife"],
      fileName: () => "viewer.js",
      cssFileName: "viewer",
    },
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
        assetFileNames: "viewer.[ext]",
      },
    },
  },
});