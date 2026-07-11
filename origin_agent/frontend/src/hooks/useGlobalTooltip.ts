import { useEffect } from "react";

const TOOLTIP_MARGIN = 10;
const TOOLTIP_ARROW = 6;

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
      tooltip.textContent = text;
      tooltip.appendChild(arrow);
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
      }, 80);
    };

    const onMouseEnter = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target) return;
      const tooltipText = target.getAttribute("data-tooltip");
      if (!tooltipText) return;
      showTooltip(target, tooltipText);
    };

    const onMouseLeave = () => {
      hideTooltip();
    };

    const app = document.getElementById("root");
    if (app) {
      app.addEventListener("mouseenter", onMouseEnter, true);
      app.addEventListener("mouseleave", onMouseLeave, true);
    }

    return () => {
      if (app) {
        app.removeEventListener("mouseenter", onMouseEnter, true);
        app.removeEventListener("mouseleave", onMouseLeave, true);
      }
      if (hideTimer) clearTimeout(hideTimer);
      tooltip.remove();
    };
  }, []);
}