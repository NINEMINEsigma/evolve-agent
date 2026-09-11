/**
 * Monaco Editor 统一环境配置。
 *
 * 集中配置 Monaco 实例和 Web Worker 加载入口，供 Agentspace 主编辑器
 * 和冲突 DiffEditor 共用。应用入口在 React 渲染前调用一次
 * `configureMonacoEnvironment()`，组件不再各自执行 `loader.config()`。
 *
 * Worker 由 Vite `?worker` 机制打包为同源构建资源，远程普通 HTTP 部署下
 * 浏览器从当前应用地址加载，不依赖 CDN 或 HTTPS。
 */

import { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";

// Vite 打包的专用 Worker 构造器
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import JsonWorker from "monaco-editor/esm/vs/language/json/json.worker?worker";
import CssWorker from "monaco-editor/esm/vs/language/css/css.worker?worker";
import HtmlWorker from "monaco-editor/esm/vs/language/html/html.worker?worker";
import TsWorker from "monaco-editor/esm/vs/language/typescript/ts.worker?worker";

let configured = false;

/**
 * 幂等配置 Monaco 环境和 `@monaco-editor/react` loader。
 *
 * 设置 `MonacoEnvironment.getWorker` 按 language label 路由到对应 Worker
 * 构造器，并注册本地打包的 Monaco 实例。重复调用安全且无副作用。
 */
export function configureMonacoEnvironment(): void {
  if (configured) return;
  configured = true;

  globalThis.MonacoEnvironment = {
    getWorker(_moduleId: string, label: string): Worker {
      switch (label) {
        case "json":
          return new JsonWorker();
        case "css":
        case "scss":
        case "less":
          return new CssWorker();
        case "html":
        case "handlebars":
        case "razor":
          return new HtmlWorker();
        case "typescript":
        case "javascript":
          return new TsWorker();
        default:
          return new EditorWorker();
      }
    },
  };

  loader.config({ monaco });
}
