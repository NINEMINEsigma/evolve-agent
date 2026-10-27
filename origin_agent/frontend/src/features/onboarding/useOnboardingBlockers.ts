import { useLayoutEffect, useState } from "react";
import { ONBOARDING } from "./constants";
import { hasBlockingOnboardingDialog } from "./targets";

/** 引导局部兼容现有模态窗口，不读取正文或建立全局模态注册表。 */
export function useOnboardingBlockers(enabled: boolean): boolean {
  const [blocked, setBlocked] = useState(false);
  useLayoutEffect(() => {
    if (!enabled) {
      setBlocked(false);
      return;
    }
    let frame = 0;
    const check = () => {
      frame = 0;
      const next = hasBlockingOnboardingDialog();
      setBlocked((previous) => previous === next ? previous : next);
    };
    const schedule = () => {
      if (!frame) frame = window.requestAnimationFrame(check);
    };
    const observer = new MutationObserver((records) => {
      if (records.some((record) => !(record.target instanceof Element)
        || !record.target.closest(ONBOARDING.ROOT_SELECTOR))) schedule();
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["class", "style", "hidden", "aria-hidden", "role", "aria-modal"],
    });
    window.addEventListener("resize", schedule);
    document.addEventListener("visibilitychange", schedule);
    check();
    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", schedule);
      document.removeEventListener("visibilitychange", schedule);
    };
  }, [enabled]);
  return enabled && blocked;
}
