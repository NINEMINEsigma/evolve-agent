import labels from "../content/zh-CN.json";

interface CanvasFrame {
  source: HTMLCanvasElement;
  image: HTMLImageElement;
  rect: DOMRect;
  width: number;
  height: number;
  visibility: string;
  priority: string;
}

function visible(element: Element): boolean {
  const rect = element.getBoundingClientRect();
  const style = getComputedStyle(element);
  return rect.width > 0 && rect.height > 0 && style.visibility === "visible" && style.display !== "none";
}

/** 定格当前动画与媒体，不停止 React、心跳或浏览器时钟。 */
export function freezePreviewFrame(): () => void {
  const animations: Animation[] = [];
  const media: HTMLMediaElement[] = [];
  const frames: CanvasFrame[] = [];
  let active = true;
  let frameId = 0;
  const originalCanvases = [...document.querySelectorAll("canvas")].filter(visible);
  const restore = () => {
    if (!active) return;
    active = false;
    cancelAnimationFrame(frameId);
    window.removeEventListener("resize", invalidate);
    window.removeEventListener("scroll", invalidate, true);
    window.visualViewport?.removeEventListener("resize", invalidate);
    window.visualViewport?.removeEventListener("scroll", invalidate);
    for (const frame of frames) {
      frame.image.remove();
      if (frame.visibility) frame.source.style.setProperty("visibility", frame.visibility, frame.priority);
      else frame.source.style.removeProperty("visibility");
    }
    for (const animation of animations) if (animation.playState === "paused") animation.play();
    for (const element of media) {
      if (element.isConnected && element.paused && !element.ended) {
        void element.play().catch(() => {
          // 浏览器可能撤销自动播放许可；不把恢复拒绝伪装成成功。
          window.dispatchEvent(new CustomEvent("preview:media-resume-blocked"));
        });
      }
    }
  };
  function invalidate() {
    if (!active) return;
    restore();
    window.dispatchEvent(new CustomEvent("preview:frame-invalidated", { detail: labels.ui.frameInvalidated }));
  }
  try {
    for (const animation of document.getAnimations()) {
      const effect = animation.effect;
      const target = effect instanceof KeyframeEffect ? effect.target : null;
      if (target instanceof Element && target.closest(".preview-controls, .preview-faults")) continue;
      if (animation.playState === "running") { animations.push(animation); animation.pause(); }
    }
    for (const element of document.querySelectorAll<HTMLMediaElement>("audio, video")) {
      if (!element.paused && !element.ended) { media.push(element); element.pause(); }
    }
    for (const source of originalCanvases) {
      const rect = source.getBoundingClientRect();
      const style = getComputedStyle(source);
      const image = document.createElement("img");
      image.className = "preview-canvas-frame";
      image.alt = "";
      image.setAttribute("aria-hidden", "true");
      // 同一父节点、同一堆叠层级；绝不把背景 Canvas 提升到消息上方。
      image.style.cssText = "position:absolute;pointer-events:none;max-width:none;max-height:none;";
      image.style.left = `${source.offsetLeft}px`;
      image.style.top = `${source.offsetTop}px`;
      image.style.width = `${source.offsetWidth}px`;
      image.style.height = `${source.offsetHeight}px`;
      image.style.zIndex = style.zIndex;
      image.style.transform = style.transform;
      image.style.transformOrigin = style.transformOrigin;
      image.style.borderRadius = style.borderRadius;
      image.style.opacity = style.opacity;
      image.style.filter = style.filter;
      image.style.clipPath = style.clipPath;
      image.style.objectFit = style.objectFit;
      image.src = source.toDataURL("image/png");
      frames.push({ source, image, rect, width: source.width, height: source.height,
        visibility: source.style.getPropertyValue("visibility"), priority: source.style.getPropertyPriority("visibility") });
      source.style.setProperty("visibility", "hidden");
      source.after(image);
    }
    const check = () => {
      if (!active) return;
      // 原 Canvas visibility 被暂时隐藏；以其存在性、几何和像素尺寸检测失效。
      const canvases = [...document.querySelectorAll("canvas")].filter((canvas) => originalCanvases.includes(canvas) || visible(canvas));
      if (canvases.length !== originalCanvases.length || frames.some((frame) => {
        const rect = frame.source.getBoundingClientRect();
        return !frame.source.isConnected || frame.source.width !== frame.width || frame.source.height !== frame.height
          || Math.abs(rect.x - frame.rect.x) > 0.5 || Math.abs(rect.y - frame.rect.y) > 0.5
          || Math.abs(rect.width - frame.rect.width) > 0.5 || Math.abs(rect.height - frame.rect.height) > 0.5;
      })) { invalidate(); return; }
      frameId = requestAnimationFrame(check);
    };
    window.addEventListener("resize", invalidate);
    window.addEventListener("scroll", invalidate, true);
    window.visualViewport?.addEventListener("resize", invalidate);
    window.visualViewport?.addEventListener("scroll", invalidate);
    frameId = requestAnimationFrame(check);
    return restore;
  } catch (cause) { restore(); throw cause; }
}
