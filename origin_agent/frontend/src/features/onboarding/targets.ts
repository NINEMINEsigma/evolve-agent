import { ONBOARDING } from "./constants";

export class OnboardingTargetError extends Error {
  constructor() {
    super("Onboarding target did not become visible and stable before the deadline");
    this.name = "OnboardingTargetError";
  }
}

export function onboardingAbortError(): DOMException {
  return new DOMException("Onboarding preparation was cancelled", "AbortError");
}

/** 检查祖先链，不能把常驻挂载的隐藏 Tab 当作可用目标。 */
export function isOnboardingElementDisplayed(element: HTMLElement): boolean {
  if (!element.isConnected) return false;
  for (let current: HTMLElement | null = element; current; current = current.parentElement) {
    const style = getComputedStyle(current);
    if (current.hidden || current.getAttribute("aria-hidden") === "true"
      || style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse") {
      return false;
    }
  }
  return true;
}

export function isOnboardingElementVisible(element: HTMLElement): boolean {
  if (!isOnboardingElementDisplayed(element)) return false;
  const rect = element.getBoundingClientRect();
  const viewport = window.visualViewport;
  const left = viewport?.offsetLeft ?? 0;
  const top = viewport?.offsetTop ?? 0;
  const right = left + (viewport?.width ?? window.innerWidth);
  const bottom = top + (viewport?.height ?? window.innerHeight);
  return rect.width > 0 && rect.height > 0
    && rect.right > left && rect.bottom > top && rect.left < right && rect.top < bottom;
}

export function hasBlockingOnboardingDialog(): boolean {
  return Array.from(document.querySelectorAll<HTMLElement>(ONBOARDING.DIALOG_SELECTOR))
    .some((element) => !element.closest(ONBOARDING.ROOT_SELECTOR)
      // 对话框已进入展示态时立即阻挡，不等待其入场动画产生非零尺寸。
      && isOnboardingElementDisplayed(element));
}

export function waitForOnboardingTarget(selector: string, signal: AbortSignal): Promise<HTMLElement> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(signal.reason ?? onboardingAbortError());
      return;
    }
    let frame = 0;
    let settled = false;
    let previous: { element: HTMLElement; rect: DOMRect } | null = null;
    let stableFrames = 0;
    const cleanup = () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timeout);
      signal.removeEventListener("abort", onAbort);
    };
    const fail = (error: unknown) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };
    const onAbort = () => fail(signal.reason ?? onboardingAbortError());
    const timeout = window.setTimeout(() => fail(new OnboardingTargetError()), ONBOARDING.TARGET_TIMEOUT_MS);
    const sample = () => {
      try {
        const element = document.querySelector<HTMLElement>(selector);
        if (element && isOnboardingElementVisible(element)) {
          const rect = element.getBoundingClientRect();
          const tolerance = ONBOARDING.GEOMETRY_TOLERANCE_PX;
          const stable = previous?.element === element
            && Math.abs(previous.rect.x - rect.x) <= tolerance
            && Math.abs(previous.rect.y - rect.y) <= tolerance
            && Math.abs(previous.rect.width - rect.width) <= tolerance
            && Math.abs(previous.rect.height - rect.height) <= tolerance;
          stableFrames = stable ? stableFrames + 1 : 1;
          previous = { element, rect };
          if (stableFrames >= ONBOARDING.STABLE_FRAMES) {
            settled = true;
            cleanup();
            resolve(element);
            return;
          }
        } else {
          previous = null;
          stableFrames = 0;
        }
        frame = window.requestAnimationFrame(sample);
      } catch (error) {
        fail(error);
      }
    };
    signal.addEventListener("abort", onAbort, { once: true });
    frame = window.requestAnimationFrame(sample);
  });
}
