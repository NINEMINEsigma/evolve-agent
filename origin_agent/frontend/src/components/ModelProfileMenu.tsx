import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import type { LlmProfileManager } from "../hooks/useLlmProfiles";
import { MODEL_MENU } from "../constants/llmProfile";
import PopupLayer from "./primitives/PopupLayer";

interface ModelProfileMenuProps {
  open: boolean;
  anchorRef: RefObject<HTMLButtonElement>;
  manager: LlmProfileManager;
  onClose: () => void;
}

export default function ModelProfileMenu({ open, anchorRef, manager, onClose }: ModelProfileMenuProps) {
  const root = useRef<HTMLDivElement | null>(null);
  const latest = useRef({ manager, onClose });
  latest.current = { manager, onClose };
  const [layout, setLayout] = useState({ x: MODEL_MENU.VIEWPORT_MARGIN as number, y: MODEL_MENU.VIEWPORT_MARGIN as number, width: MODEL_MENU.WIDTH as number, maxHeight: MODEL_MENU.MAX_HEIGHT as number });
  const closeAndFocus = useCallback(() => {
    latest.current.onClose();
    anchorRef.current?.focus({ preventScroll: true });
  }, [anchorRef]);
  useLayoutEffect(() => {
    if (!open) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const anchor = anchorRef.current;
      if (!anchor) return;
      const rect = anchor.getBoundingClientRect();
      const viewport = window.visualViewport;
      const left = viewport?.offsetLeft ?? 0, top = viewport?.offsetTop ?? 0;
      const width = viewport?.width ?? window.innerWidth, height = viewport?.height ?? window.innerHeight;
      const margin = MODEL_MENU.VIEWPORT_MARGIN;
      const menuWidth = Math.max(0, Math.min(MODEL_MENU.WIDTH, width - margin * 2));
      const maxHeight = Math.max(0, Math.min(MODEL_MENU.MAX_HEIGHT, height - margin * 2));
      const actualHeight = Math.min(root.current?.getBoundingClientRect().height ?? maxHeight, maxHeight);
      const x = Math.max(left + margin, Math.min(rect.left + rect.width / 2 - menuWidth / 2, left + width - menuWidth - margin));
      const preferredY = rect.bottom + MODEL_MENU.ANCHOR_GAP;
      const y = Math.max(top + margin, Math.min(preferredY, top + height - actualHeight - margin));
      setLayout((previous) => previous.x === x && previous.y === y && previous.width === menuWidth && previous.maxHeight === maxHeight
        ? previous : { x, y, width: menuWidth, maxHeight });
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(update); };
    const onScroll = (event: Event) => {
      // 菜单内部滚动不需要重定位，也不触发关闭或选择。
      if (event.target instanceof Node && root.current?.contains(event.target)) return;
      schedule();
    };
    update();
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", onScroll, true);
    window.visualViewport?.addEventListener("resize", schedule);
    window.visualViewport?.addEventListener("scroll", schedule);
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(schedule) : null;
    if (anchorRef.current) observer?.observe(anchorRef.current);
    if (root.current) observer?.observe(root.current);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", onScroll, true);
      window.visualViewport?.removeEventListener("resize", schedule);
      window.visualViewport?.removeEventListener("scroll", schedule);
    };
  }, [open, anchorRef]);

  useEffect(() => {
    if (!open) return;
    const inside = (target: EventTarget | null) => target instanceof Node
      && (root.current?.contains(target) || anchorRef.current?.contains(target));
    const outside = (event: PointerEvent) => { if (!inside(event.target)) latest.current.onClose(); };
    const focus = (event: FocusEvent) => { if (!inside(event.target)) latest.current.onClose(); };
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeAndFocus(); }
    };
    const selected = root.current?.querySelector<HTMLElement>("[aria-pressed='true']");
    (selected ?? root.current?.querySelector<HTMLElement>("button:not(:disabled)"))?.focus({ preventScroll: true });
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("focusin", focus);
    document.addEventListener("keydown", key, true);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("focusin", focus);
      document.removeEventListener("keydown", key, true);
    };
  }, [open, anchorRef, closeAndFocus]);
  useEffect(() => {
    if (!open || document.activeElement !== anchorRef.current) return;
    // 打开时目录尚未就绪：候选到达后再把键盘焦点交给当前项。
    const selected = root.current?.querySelector<HTMLElement>("[aria-pressed='true']");
    (selected ?? root.current?.querySelector<HTMLElement>("button:not(:disabled)"))?.focus({ preventScroll: true });
  }, [open, anchorRef, manager.profilesStatus, manager.profiles.length, manager.selectionStatus]);
  if (!open) return null;
  const retry = () => {
    void manager.refreshProfiles().then(() => manager.refreshSessionSelection()).catch(() => {});
  };
  return <PopupLayer position={{ x: layout.x, y: layout.y }} closeOnOutsideClick={false} closeOnEsc={false}
    className="model-profile-menu" containerRef={root} style={{ width: layout.width, maxHeight: layout.maxHeight }}>
    <div id={anchorRef.current?.getAttribute("aria-controls") ?? undefined} aria-label="选择会话待用模型">
      <div className="model-profile-menu-heading"><strong>会话待用模型</strong><span>发送消息或重新生成时生效</span></div>
      {manager.selectionStatus === "loading" && <div className="model-profile-menu-notice" role="status">正在读取会话配置，可直接选择下方模型。</div>}
      {(manager.selectionError || manager.profilesError || manager.profilesWarning) && <div className="model-profile-menu-notice" role="alert">
        {manager.selectionError || manager.profilesError || manager.profilesWarning}<button type="button" onClick={retry}>重新读取</button>
      </div>}
      {manager.storageWarning && <div className="model-profile-menu-notice">{manager.storageWarning}</div>}
      {manager.profiles.map((profile) => <button type="button" key={profile.name} className="model-profile-option"
        aria-pressed={profile.name === manager.activeProfileName && manager.selectionStatus === "ready"}
        disabled={!manager.sessionId || manager.profilesStatus !== "ready"}
        onClick={() => { manager.setActiveProfile(profile.name); closeAndFocus(); }}>
        <span className="model-profile-option-text"><strong>{profile.name}</strong><span>{profile.model || "未设置模型"}</span></span>
        <span className="model-profile-check" aria-hidden>{profile.name === manager.activeProfileName && manager.selectionStatus === "ready" ? "✓" : ""}</span>
      </button>)}
      {manager.profilesStatus === "ready" && !manager.profiles.length && <div className="model-profile-menu-notice">尚无模型配置，请从右侧模型配置抽屉新增。</div>}
    </div>
  </PopupLayer>;
}
