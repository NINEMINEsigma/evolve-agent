import { useEffect } from "react";
import { DIMENSIONS } from "../constants/dimensions";
import { TIMING } from "../constants/timing";

const CONTEXT_TOOLTIP_VARIANT = "context-usage";

function readTooltipNumber(host: HTMLElement, attribute: string): number | null {
  const value = host.getAttribute(attribute);
  if (value === null || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatTooltipNumber(value: number): string {
  return value.toLocaleString();
}

function renderContextUsageTooltip(tooltip: HTMLDivElement, host: HTMLElement): boolean {
  const contextTokens = readTooltipNumber(host, "data-tooltip-context-tokens");
  const maxContextTokens = readTooltipNumber(host, "data-tooltip-max-context-tokens");
  const tokenUsage = readTooltipNumber(host, "data-tooltip-token-usage");
  if (contextTokens === null || maxContextTokens === null || tokenUsage === null || maxContextTokens <= 0) {
    return false;
  }

  const percent = Math.min(100, Math.max(0, (contextTokens / maxContextTokens) * 100));
  const remainingTokens = maxContextTokens - contextTokens;
  const usageTone = percent >= 90 ? "danger" : percent >= 75 ? "warning" : "normal";
  const createText = (tagName: string, className: string, text: string) => {
    const element = document.createElement(tagName);
    element.className = className;
    element.textContent = text;
    return element;
  };

  const content = document.createElement("div");
  content.className = "global-tooltip-context-usage";

  const heading = document.createElement("div");
  heading.className = "global-tooltip-context-heading";
  heading.append(
    createText("span", "global-tooltip-context-title", "上下文用量"),
    createText("span", `global-tooltip-context-percent global-tooltip-context-percent--${usageTone}`, `${Math.round(percent)}%`),
  );

  const progress = document.createElement("div");
  progress.className = "global-tooltip-context-progress";
  const progressValue = document.createElement("div");
  progressValue.className = `global-tooltip-context-progress-value global-tooltip-context-progress-value--${usageTone}`;
  progressValue.style.width = `${percent}%`;
  progress.appendChild(progressValue);

  const stats = document.createElement("div");
  stats.className = "global-tooltip-context-stats";
  const usedRow = document.createElement("div");
  usedRow.className = "global-tooltip-context-stat";
  usedRow.append(
    createText("span", "global-tooltip-context-stat-label", "已用上下文"),
    createText("strong", "global-tooltip-context-stat-value", formatTooltipNumber(contextTokens)),
    createText("span", "global-tooltip-context-stat-detail", `/ ${formatTooltipNumber(maxContextTokens)}`),
  );
  const remainingRow = document.createElement("div");
  remainingRow.className = "global-tooltip-context-stat";
  remainingRow.append(
    createText("span", "global-tooltip-context-stat-label", "剩余空间"),
    createText(
      "strong",
      `global-tooltip-context-stat-value global-tooltip-context-stat-value--${remainingTokens < 0 ? "danger" : "normal"}`,
      remainingTokens >= 0 ? formatTooltipNumber(remainingTokens) : `超出 ${formatTooltipNumber(Math.abs(remainingTokens))}`,
    ),
  );
  const totalRow = document.createElement("div");
  totalRow.className = "global-tooltip-context-stat global-tooltip-context-stat--total";
  totalRow.append(
    createText("span", "global-tooltip-context-stat-label", "累计消耗"),
    createText("strong", "global-tooltip-context-stat-value", formatTooltipNumber(tokenUsage)),
  );
  stats.append(usedRow, remainingRow, totalRow);
  content.append(heading, progress, stats);
  tooltip.appendChild(content);
  tooltip.classList.add("global-tooltip--context-usage");
  return true;
}

export function useGlobalTooltip() {
  useEffect(() => {
    const tooltip = document.createElement("div");
    tooltip.className = "global-tooltip";
    tooltip.style.setProperty("--tooltip-viewport-margin", `${DIMENSIONS.TOOLTIP_VIEWPORT_MARGIN}px`);
    const arrow = document.createElement("div");
    arrow.className = "global-tooltip-arrow";
    tooltip.appendChild(arrow);
    document.body.appendChild(tooltip);

    let hideTimer: ReturnType<typeof setTimeout> | null = null;

    const showTooltip = (target: HTMLElement, text: string) => {
      if (hideTimer) {
        clearTimeout(hideTimer);
        hideTimer = null;
      }
      tooltip.classList.remove("global-tooltip--context-usage");
      tooltip.textContent = "";
      const renderedContextUsage = target.getAttribute("data-tooltip-variant") === CONTEXT_TOOLTIP_VARIANT
        && renderContextUsageTooltip(tooltip, target);
      if (!renderedContextUsage) tooltip.textContent = text;
      tooltip.appendChild(arrow);
      // 在中性坐标按最终宽度布局，避免继承上一次靠边位置的可用空间。
      tooltip.style.top = "0px";
      tooltip.style.left = "0px";
      tooltip.style.right = "";
      tooltip.style.bottom = "";
      tooltip.style.maxWidth = "";

      const rect = target.getBoundingClientRect();
      // offset 尺寸不包含显隐动画的 transform，且已包含最终换行后的高度。
      const tipWidth = tooltip.offsetWidth;
      const tipHeight = tooltip.offsetHeight;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const margin = DIMENSIONS.TOOLTIP_VIEWPORT_MARGIN;
      const gap = DIMENSIONS.TOOLTIP_ANCHOR_GAP;
      const anchorCenter = rect.left + rect.width / 2;
      const spaceBelow = vh - margin - rect.bottom - gap;
      const spaceAbove = rect.top - gap - margin;
      const placeAbove = tipHeight > spaceBelow && spaceAbove > spaceBelow;
      const preferredTop = placeAbove ? rect.top - tipHeight - gap : rect.bottom + gap;
      const top = Math.max(margin, Math.min(preferredTop, vh - margin - tipHeight));
      const left = Math.max(margin, Math.min(anchorCenter - tipWidth / 2, vw - margin - tipWidth));

      tooltip.style.top = `${top}px`;
      tooltip.style.left = `${left}px`;

      const arrowInset = Math.min(DIMENSIONS.TOOLTIP_ARROW_EDGE_INSET, tipWidth / 2);
      const arrowCenter = Math.max(arrowInset, Math.min(anchorCenter - left, tipWidth - arrowInset));
      arrow.className = `global-tooltip-arrow ${placeAbove ? "bottom" : "top"}`;
      arrow.style.top = "";
      arrow.style.bottom = "";
      arrow.style.right = "";
      // 仅在此补偿一次箭头半宽，并将主体边框坐标换算到绝对定位包含块。
      arrow.style.left = `${arrowCenter - tooltip.clientLeft - arrow.offsetWidth / 2}px`;
      tooltip.classList.add("visible");
    };

    const hideTooltip = () => {
      if (hideTimer) clearTimeout(hideTimer);
      hideTimer = setTimeout(() => {
        tooltip.classList.remove("visible");
      }, TIMING.TOOLTIP_HIDE_DELAY);
    };

    const onMouseEnter = (e: MouseEvent) => {
      const target = e.target;
      if (!(target instanceof Element)) return;
      const host = target.closest<HTMLElement>("[data-tooltip]");
      if (!host) return;
      const tooltipText = host.getAttribute("data-tooltip");
      if (!tooltipText) return;
      showTooltip(host, tooltipText);
    };

    const onMouseLeave = (e: MouseEvent) => {
      const target = e.target;
      const related = e.relatedTarget;
      if (!(target instanceof Element) || !(related instanceof Node)) {
        hideTooltip();
        return;
      }
      // 从触发源向上查找最近的 tooltip 宿主元素（带 data-tooltip）
      const host = target.closest("[data-tooltip]");
      if (host && (host === related || host.contains(related))) {
        // 鼠标仍在宿主元素范围内（只是从子元素移到另一个子元素），不隐藏
        return;
      }
      hideTooltip();
    };

    // Native capture listeners on the whole document so data-tooltip also works
    // inside createPortal content rendered to document.body (e.g. MediaDetailsWindow).
    document.addEventListener("mouseenter", onMouseEnter, true);
    document.addEventListener("mouseleave", onMouseLeave, true);

    return () => {
      document.removeEventListener("mouseenter", onMouseEnter, true);
      document.removeEventListener("mouseleave", onMouseLeave, true);
      if (hideTimer) clearTimeout(hideTimer);
      tooltip.remove();
    };
  }, []);
}
