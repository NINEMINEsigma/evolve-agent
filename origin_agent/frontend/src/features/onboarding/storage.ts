import { STORAGE_KEYS } from "../../constants/storage";

export function shouldOfferOnboarding(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEYS.ONBOARDING_COMPLETED) !== "true";
  } catch {
    // 仅存储边界降级；本页去重由控制器负责。
    return true;
  }
}

export function markOnboardingDismissed(): void {
  try {
    localStorage.setItem(STORAGE_KEYS.ONBOARDING_COMPLETED, "true");
  } catch {
    // 浏览器禁止存储时仍允许退出，但不承诺跨刷新记忆。
  }
}
