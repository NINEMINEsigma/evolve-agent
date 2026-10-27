import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { Joyride, STATUS, EVENTS } from "react-joyride";
import { ONBOARDING } from "../features/onboarding/constants";
import { onboardingLabels as labels } from "../features/onboarding/labels";
import { buildOnboardingSteps } from "../features/onboarding/steps";
import OnboardingPreparing from "../features/onboarding/OnboardingPreparing";
import type { OnboardingStepsOptions, OnboardingTourController } from "../features/onboarding/types";

interface OnboardingTourProps {
  controller: OnboardingTourController;
  isMobile: boolean;
  archived: boolean;
  tabs: OnboardingStepsOptions["tabs"];
}

export default function OnboardingTour(props: OnboardingTourProps) {
  const { controller } = props;
  if (!controller.run) return null;
  return <ActiveTour key={`${controller.run.id}:${controller.renderEpoch}`} {...props} />;
}

function ActiveTour({ controller, isMobile, archived, tabs }: OnboardingTourProps) {
  const [portal, setPortal] = useState<HTMLDivElement | null>(null);
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const activeRef = useRef(false);
  const prepareToken = useRef(0);
  const ignoredErrors = useRef(new Set<unknown>());
  const latest = useRef(controller);
  latest.current = controller;
  // 每个实例固定内容与 before；环境变化由控制器中断，不替换步骤数组。
  const [steps] = useState(() => buildOnboardingSteps({
    archived, isMobile, tabs,
    prepare: async (id) => {
      const token = ++prepareToken.current;
      try {
        await controller.prepareStep(id);
      } catch (error) {
        if (!activeRef.current || token !== prepareToken.current
          || (error instanceof DOMException && error.name === "AbortError")) {
          ignoredErrors.current.add(error);
        }
        throw error;
      }
    },
  }));

  useLayoutEffect(() => {
    activeRef.current = true;
    const root = document.createElement("div");
    root.className = "onboarding-root";
    root.setAttribute("data-onboarding-root", "");
    root.style.setProperty("--onboarding-max-width", `${ONBOARDING.MAX_WIDTH_PX}px`);
    root.style.setProperty("--onboarding-margin", `${ONBOARDING.VIEWPORT_MARGIN_PX}px`);
    root.style.setProperty("--onboarding-radius", `${ONBOARDING.RADIUS_PX}px`);
    root.style.setProperty("--onboarding-z-index", String(ONBOARDING.Z_INDEX));
    document.body.appendChild(root);
    setPortal(root);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      latest.current.finish("skipped");
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      activeRef.current = false;
      prepareToken.current += 1;
      document.removeEventListener("keydown", onKeyDown, true);
      root.remove();
    };
  }, []);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const change = () => setReducedMotion(query.matches);
    query.addEventListener("change", change);
    return () => query.removeEventListener("change", change);
  }, []);

  if (!portal || !portal.isConnected) return null;
  const buttonStyle: CSSProperties = {
    borderRadius: "var(--radius-sm)", fontSize: 13, padding: "8px 10px", minHeight: 40,
  };
  return createPortal(
    <>
      <Joyride
        continuous
        run
        steps={steps}
        portalElement={portal}
        loaderComponent={null}
        onEvent={(data) => {
          if (!activeRef.current) return;
          if (data.type === EVENTS.ERROR || data.type === EVENTS.TARGET_NOT_FOUND) {
            if (ignoredErrors.current.has(data.error)) {
              ignoredErrors.current.delete(data.error);
              return;
            }
            latest.current.reportFailure(data.error);
            return;
          }
          if (data.status === STATUS.FINISHED) latest.current.finish("completed");
          else if (data.status === STATUS.SKIPPED) latest.current.finish("skipped");
        }}
        options={{
          buttons: ["back", "skip", "close", "primary"],
          primaryColor: "var(--accent)", backgroundColor: "var(--bg-secondary)",
          textColor: "var(--text-primary)", arrowColor: "var(--bg-secondary)",
          overlayColor: "rgba(0, 0, 0, 0.6)", zIndex: ONBOARDING.Z_INDEX,
          spotlightPadding: ONBOARDING.SPOTLIGHT_PADDING_PX, spotlightRadius: ONBOARDING.RADIUS_PX,
          showProgress: true, skipBeacon: true,
          width: `min(${ONBOARDING.MAX_WIDTH_PX}px, calc(100vw - ${ONBOARDING.VIEWPORT_MARGIN_PX * 2}px))`,
          closeButtonAction: "skip", dismissKeyAction: false, overlayClickAction: false,
          blockTargetInteraction: true,
          scrollDuration: reducedMotion ? 0 : ONBOARDING.SCROLL_DURATION_MS,
          beforeTimeout: ONBOARDING.BEFORE_TIMEOUT_MS, targetWaitTimeout: ONBOARDING.TARGET_TIMEOUT_MS,
        }}
        styles={{
          tooltip: {
            backgroundColor: "var(--bg-secondary)", color: "var(--text-primary)",
            borderRadius: ONBOARDING.RADIUS_PX, fontFamily: "inherit", fontSize: 14,
            maxHeight: `calc(100dvh - ${ONBOARDING.VIEWPORT_MARGIN_PX * 2}px)`,
            display: "flex", flexDirection: "column", overflow: "hidden",
          },
          tooltipContainer: { display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" },
          tooltipTitle: { fontSize: 16, fontWeight: 600, flexShrink: 0 },
          tooltipContent: { fontSize: 14, lineHeight: 1.6, minHeight: 0, overflowY: "auto", padding: "12px 0" },
          tooltipFooter: { flexShrink: 0, flexWrap: "wrap", gap: 6 },
          buttonPrimary: { ...buttonStyle, backgroundColor: "var(--accent)", color: "var(--bg-primary)" },
          buttonBack: { ...buttonStyle, backgroundColor: "var(--bg-hover)", color: "var(--text-primary)" },
          buttonSkip: { ...buttonStyle, color: "var(--text-secondary)" },
          buttonClose: { color: "var(--text-secondary)" },
        }}
        locale={labels.buttons}
      />
      {controller.preparing && <OnboardingPreparing onSkip={() => latest.current.finish("skipped")} />}
    </>,
    portal,
  );
}
