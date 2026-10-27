import { COLLOQUY_SID } from "@origin/constants/session";
import { PREVIEW, TAB_IDS } from "./constants";
import content from "./content/zh-CN.json";
import type { PreviewOptions, PreviewScene } from "./types";

export const SCENES: readonly PreviewScene[] = [
  { id: "showcase", label: content.scenes.showcase, sessionId: PREVIEW.mainSession },
  { id: "empty", label: content.scenes.empty, sessionId: PREVIEW.emptySession },
  { id: "multi", label: content.scenes.multi, sessionId: PREVIEW.multiSession },
  { id: "approval", label: content.scenes.approval, sessionId: PREVIEW.approvalSession },
  { id: "question", label: content.scenes.question, sessionId: PREVIEW.questionSession },
  { id: "archived", label: content.scenes.archived, sessionId: PREVIEW.archivedSession },
  { id: "visual", label: content.scenes.visual, sessionId: PREVIEW.mainSession },
  { id: "onboarding", label: content.scenes.onboarding, sessionId: PREVIEW.mainSession },
];

export function parsePreviewOptions(location: Pick<Location, "pathname" | "search">): PreviewOptions {
  const params = new URLSearchParams(location.search);
  const sceneId = params.get("scene") ?? "showcase";
  const scene = SCENES.find((item) => item.id === sceneId);
  if (!scene) throw new Error(content.errors.scene);

  const tabId = params.get("tab") ?? "chat";
  const tab = TAB_IDS.find((item) => item === tabId);
  if (!tab) throw new Error(content.errors.tab);

  const sessionId = params.get("session") ?? scene.sessionId;
  const seedSessionIds: readonly string[] = [
    PREVIEW.mainSession, PREVIEW.emptySession, PREVIEW.multiSession,
    PREVIEW.archivedSession, PREVIEW.approvalSession, PREVIEW.questionSession,
    COLLOQUY_SID,
  ];
  if (!seedSessionIds.includes(sessionId)) throw new Error(content.errors.session);

  const controls = params.get("controls") ?? "0";
  if (controls !== "0" && controls !== "1") throw new Error(content.errors.controls);
  const editor = location.pathname === "/agentspace" || location.pathname.startsWith("/agentspace/");
  if (location.pathname !== "/" && !editor) throw new Error(content.errors.path);

  return { scene: scene.id, tab, sessionId, controls: controls === "1", editor };
}
