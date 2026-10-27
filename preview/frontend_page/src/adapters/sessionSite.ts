import { useEffect, useState } from "react";
import { zipSync, strToU8 } from "fflate";
import { useSessionSite as useOriginalSessionSite } from "@preview-original/session-site";
import type { SessionSiteState } from "@preview-original/session-site";
import siteHtml from "../../public/demo/site/index.html?raw";
import labels from "../content/zh-CN.json";
export type { SiteStatus, SessionSiteState } from "@preview-original/session-site";

interface ZipLease { key: string; url: string }

export function useSessionSite(sessionId: string | undefined): SessionSiteState {
  const original = useOriginalSessionSite(sessionId);
  const [lease, setLease] = useState<ZipLease | null>(null);
  const key = original.status === "ready" && sessionId ? `${sessionId}:${original.reloadKey}` : "";
  useEffect(() => {
    if (!key) { setLease(null); return; }
    const bytes = zipSync({
      "index.html": strToU8(siteHtml),
      "README.txt": strToU8(labels.ui.exportReadme),
    });
    const url = URL.createObjectURL(new Blob([new Uint8Array(bytes)], { type: "application/zip" }));
    setLease({ key, url });
    const revoke = () => URL.revokeObjectURL(url);
    window.addEventListener("pagehide", revoke, { once: true });
    return () => { window.removeEventListener("pagehide", revoke); revoke(); };
  }, [key]);
  // 尚未准备 ZIP 时绝不暴露原 /zip/ 端点；原 hook 的探测、刷新和 iframe 地址均不变。
  return {
    ...original,
    urls: original.urls ? { ...original.urls, zipUrl: lease?.key === key ? lease.url : "" } : null,
  };
}
