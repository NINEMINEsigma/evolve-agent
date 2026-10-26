import { useEffect } from "react";
import { TIMING } from "../constants/timing";

const TOOLTIP_MARGIN = 10;
const TOOLTIP_ARROW = 6;
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
      tooltip.style.maxWidth = "";
      tooltip.classList.add("visible");

      const rect = target.getBoundingClientRect();
      const tipRect = tooltip.getBoundingClientRect();
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      let top = rect.bottom + TOOLTIP_MARGIN + TOOLTIP_ARROW;
      let left = rect.left + rect.width / 2 - tipRect.width / 2;
      let arrowDir: "top" | "bottom" = "top";

      if (top + tipRect.height > vh - TOOLTIP_MARGIN) {
        top = rect.top - tipRect.height - TOOLTIP_MARGIN - TOOLTIP_ARROW;
        arrowDir = "bottom";
      }
      if (left < TOOLTIP_MARGIN) left = TOOLTIP_MARGIN;
      if (left + tipRect.width > vw - TOOLTIP_MARGIN) {
        left = vw - tipRect.width - TOOLTIP_MARGIN;
      }
      if (tipRect.width > vw - TOOLTIP_MARGIN * 2) {
        left = TOOLTIP_MARGIN;
        tooltip.style.maxWidth = `${vw - TOOLTIP_MARGIN * 2}px`;
      }

      tooltip.style.top = `${top}px`;
      tooltip.style.left = `${left}px`;

      arrow.className = `global-tooltip-arrow ${arrowDir}`;
      if (arrowDir === "top") {
        arrow.style.top = "-5px";
        arrow.style.left = `${rect.left + rect.width / 2 - left - 5}px`;
        arrow.style.bottom = "";
        arrow.style.right = "";
      } else {
        arrow.style.bottom = "-5px";
        arrow.style.left = `${rect.left + rect.width / 2 - left - 5}px`;
        arrow.style.top = "";
        arrow.style.right = "";
      }
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
