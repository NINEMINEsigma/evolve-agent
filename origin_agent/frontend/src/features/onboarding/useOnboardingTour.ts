import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { EMPTY_PRESENTATION, ONBOARDING, ONBOARDING_STEPS } from "./constants";
import { onboardingLabels as labels } from "./labels";
import { markOnboardingDismissed, shouldOfferOnboarding } from "./storage";
import {
  hasBlockingOnboardingDialog, isOnboardingElementVisible, onboardingAbortError,
  OnboardingTargetError, waitForOnboardingTarget,
} from "./targets";
import { useOnboardingBlockers } from "./useOnboardingBlockers";
import type {
  OnboardingAdapters, OnboardingEnvironment, OnboardingExitReason, OnboardingPresentation,
  OnboardingRun, OnboardingStepId, OnboardingTourController,
} from "./types";

export function useOnboardingTour(
  environment: OnboardingEnvironment,
  adapters: OnboardingAdapters,
  onboardingReady: boolean,
): OnboardingTourController {
  const [offerAutomatically] = useState(shouldOfferOnboarding);
  const [run, setRun] = useState<OnboardingRun | null>(null);
  const [presentation, setPresentation] = useState<OnboardingPresentation>(EMPTY_PRESENTATION);
  const [preparing, setPreparing] = useState(false);
  const [renderEpoch, setRenderEpoch] = useState(0);
  const [replayPending, setReplayPending] = useState(false);
  const current = useRef({ environment, adapters, onboardingReady });
  current.current = { environment, adapters, onboardingReady };
  const runRef = useRef<OnboardingRun | null>(null);
  const snapshotRef = useRef({ archived: false, isMobile: false });
  const presentationRef = useRef(EMPTY_PRESENTATION);
  const preparingRef = useRef(false);
  const replayPendingRef = useRef(false);
  const autoAttempted = useRef(false);
  const nextRunId = useRef(0);
  const preparationId = useRef(0);
  const preparation = useRef<AbortController | null>(null);
  const preparationDeadline = useRef<number | null>(null);
  const epochRef = useRef(0);
  const lease = useRef(0);
  const mounted = useRef(false);
  const restoreFrame = useRef(0);
  const restoreTimer = useRef<number | null>(null);
  const dialogBlocked = useOnboardingBlockers(
    (offerAutomatically && !autoAttempted.current) || replayPending || run !== null,
  );

  const cancelPreparation = useCallback(() => {
    preparationId.current += 1;
    preparation.current?.abort(onboardingAbortError());
    preparation.current = null;
    if (preparationDeadline.current !== null) window.clearTimeout(preparationDeadline.current);
    preparationDeadline.current = null;
  }, []);

  const cancelRestoration = useCallback(() => {
    window.cancelAnimationFrame(restoreFrame.current);
    restoreFrame.current = 0;
    if (restoreTimer.current !== null) window.clearTimeout(restoreTimer.current);
    restoreTimer.current = null;
  }, []);

  const unavailableReason = useCallback((allowCommandMenu: boolean): string => {
    const { environment: env, onboardingReady: ready } = current.current;
    if (document.visibilityState !== "visible") return labels.disabled.hidden;
    if (env.locked) return labels.disabled.locked;
    if (!ready || !env.ready || !env.sessionId) return labels.disabled.ready;
    if (env.busy) return labels.disabled.busy;
    if (env.hasPendingInteraction) return labels.disabled.interaction;
    if (env.blocked || (!allowCommandMenu && env.commandMenuOpen) || hasBlockingOnboardingDialog()) {
      return labels.disabled.blocked;
    }
    return "";
  }, []);

  const finishRun = useCallback((reason: OnboardingExitReason) => {
    const ended = runRef.current;
    if (!ended || !mounted.current) return;
    const env = current.current.environment;
    const changedScope = ended.sessionId !== env.sessionId
      || env.archived !== snapshotRef.current.archived || env.isMobile !== snapshotRef.current.isMobile;
    const exitReason = changedScope || unavailableReason(false) ? "interrupted" : reason;
    // terminal 先提交到 ref，后续库事件及旧 Promise 不再拥有该运行。
    runRef.current = null;
    cancelPreparation();
    presentationRef.current = EMPTY_PRESENTATION;
    preparingRef.current = false;
    setPresentation(EMPTY_PRESENTATION);
    setPreparing(false);
    setRun(null);
    if (exitReason === "completed" || exitReason === "skipped") markOnboardingDismissed();

    if (ended.sessionId !== env.sessionId || env.locked || !env.ready) return;
    const tab = env.enabledTabs[ended.initialTab] ? ended.initialTab : "chat";
    current.current.adapters.switchTab(tab);
    cancelRestoration();
    const restoreLease = lease.current;
    const focus = ended.initialFocus;
    if (!focus || focus === document.body) return;
    const restore = () => {
      restoreFrame.current = 0;
      const latest = current.current.environment;
      if (!mounted.current || lease.current !== restoreLease || runRef.current
        || replayPendingRef.current || nextRunId.current !== ended.id
        || latest.sessionId !== ended.sessionId || unavailableReason(false)) {
        cancelRestoration();
        return;
      }
      // 等待布局恢复提交后才聚焦；隐藏/卸载的旧元素不强行召回。
      if (latest.activeTab === tab && !document.querySelector(ONBOARDING.ROOT_SELECTOR)
        && isOnboardingElementVisible(focus)) {
        cancelRestoration();
        focus.focus({ preventScroll: true });
        return;
      }
      restoreFrame.current = window.requestAnimationFrame(restore);
    };
    restoreTimer.current = window.setTimeout(cancelRestoration, ONBOARDING.TARGET_TIMEOUT_MS);
    restoreFrame.current = window.requestAnimationFrame(restore);
  }, [cancelPreparation, cancelRestoration, unavailableReason]);

  const failRun = useCallback((error: unknown) => {
    if (!runRef.current || !mounted.current) return;
    // 只输出错误类别，不把第三方异常正文或页面内容送入诊断。
    console.warn("Onboarding stopped", error instanceof OnboardingTargetError ? "target-timeout" : "preparation-error");
    finishRun("failed");
    current.current.adapters.onNotice(labels.failure);
  }, [finishRun]);

  // 资源租约独立于 run/step/renderEpoch，避免更新一步就执行卸载清理。
  useLayoutEffect(() => {
    mounted.current = true;
    lease.current += 1;
    if (runRef.current) {
      presentationRef.current = EMPTY_PRESENTATION;
      preparingRef.current = false;
      setPresentation(EMPTY_PRESENTATION);
      setPreparing(false);
      epochRef.current += 1;
      setRenderEpoch(epochRef.current);
    }
    return () => {
      mounted.current = false;
      lease.current += 1;
      cancelPreparation();
      cancelRestoration();
    };
  }, [cancelPreparation, cancelRestoration]);

  const startRun = useCallback((source: OnboardingRun["source"]) => {
    if (!mounted.current || runRef.current || unavailableReason(false)) return;
    cancelRestoration();
    const env = current.current.environment;
    const focus = source === "replay"
      ? document.querySelector<HTMLElement>(ONBOARDING.COMMAND_SELECTOR)
      : document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const next: OnboardingRun = {
      id: ++nextRunId.current, sessionId: env.sessionId, source,
      initialTab: env.activeTab, initialFocus: focus,
    };
    snapshotRef.current = { archived: env.archived, isMobile: env.isMobile };
    autoAttempted.current = true;
    runRef.current = next;
    setRun(next);
  }, [cancelRestoration, unavailableReason]);

  const requestReplay = useCallback(() => {
    if (runRef.current || unavailableReason(true)) return;
    cancelRestoration();
    replayPendingRef.current = true;
    setReplayPending(true);
  }, [cancelRestoration, unavailableReason]);

  useEffect(() => {
    if (runRef.current) {
      const active = runRef.current;
      const snapshot = snapshotRef.current;
      const step = ONBOARDING_STEPS.find((item) => item.id === presentationRef.current.stepId);
      if (unavailableReason(false) || environment.sessionId !== active.sessionId
        || environment.archived !== snapshot.archived || environment.isMobile !== snapshot.isMobile
        || (step && (!environment.enabledTabs[step.tab]
          || (!preparingRef.current && environment.activeTab !== step.tab)))) {
        finishRun("interrupted");
      }
      return;
    }
    if (replayPending) {
      // 命令菜单先关闭；其他资格消失时取消请求，不在稍后意外弹出。
      if (unavailableReason(true)) {
        replayPendingRef.current = false;
        setReplayPending(false);
      } else if (!environment.commandMenuOpen) {
        replayPendingRef.current = false;
        setReplayPending(false);
        startRun("replay");
      }
    } else if (offerAutomatically && !autoAttempted.current && !unavailableReason(false)) {
      startRun("first-visit");
    }
  }, [environment, onboardingReady, dialogBlocked, replayPending, offerAutomatically,
    run, presentation, preparing, finishRun, startRun, unavailableReason]);

  const prepare = useCallback(async (id: OnboardingStepId) => {
    const active = runRef.current;
    if (!active || !mounted.current) throw onboardingAbortError();
    const definition = ONBOARDING_STEPS.find((item) => item.id === id);
    if (!definition) throw new Error("Unknown onboarding step");
    const env = current.current.environment;
    if (unavailableReason(false) || env.sessionId !== active.sessionId || !env.enabledTabs[definition.tab]) {
      finishRun("interrupted");
      throw onboardingAbortError();
    }
    cancelPreparation();
    const token = preparationId.current;
    const activeLease = lease.current;
    const abort = new AbortController();
    preparation.current = abort;
    const ownsPreparation = () => mounted.current && lease.current === activeLease
      && runRef.current?.id === active.id && preparationId.current === token;
    const assertCurrent = () => {
      if (!ownsPreparation()) throw onboardingAbortError();
      if (abort.signal.aborted) throw abort.signal.reason;
      const latest = current.current.environment;
      if (unavailableReason(false) || latest.sessionId !== active.sessionId
        || latest.archived !== snapshotRef.current.archived || latest.isMobile !== snapshotRef.current.isMobile
        || !latest.enabledTabs[definition.tab]) {
        finishRun("interrupted");
        throw onboardingAbortError();
      }
    };
    preparationDeadline.current = window.setTimeout(() => {
      if (ownsPreparation()) abort.abort(new OnboardingTargetError());
    }, ONBOARDING.TARGET_TIMEOUT_MS);
    try {
      const next: OnboardingPresentation = {
        stepId: id, expandSidebar: id === "sidebar",
        expandInput: !env.archived && (id === "input" || id === "approval"),
      };
      presentationRef.current = next;
      preparingRef.current = true;
      setPresentation(next);
      setPreparing(true);
      assertCurrent();
      current.current.adapters.switchTab(definition.tab);
      // 两段等待共享上面的总截止和取消信号，不串联增加预算。
      await waitForOnboardingTarget(`[data-tab-panel="${definition.tab}"][data-active="true"]`, abort.signal);
      assertCurrent();
      const selector = env.archived && (id === "input" || id === "approval") ? "body" : definition.target;
      await waitForOnboardingTarget(selector, abort.signal);
      assertCurrent();
      if (current.current.environment.activeTab !== definition.tab) {
        finishRun("interrupted");
        throw onboardingAbortError();
      }
    } catch (error) {
      if (ownsPreparation()) failRun(error);
      throw error;
    } finally {
      if (ownsPreparation()) {
        if (preparationDeadline.current !== null) window.clearTimeout(preparationDeadline.current);
        preparationDeadline.current = null;
        preparation.current = null;
        preparingRef.current = false;
        setPreparing(false);
      }
    }
  }, [cancelPreparation, failRun, finishRun, unavailableReason]);

  const replayDisabledReason = run ? labels.disabled.running : unavailableReason(true);
  // 公共方法绑定当前 run/epoch；旧实例的事件不可结束下一次重看。
  return useMemo(() => {
    const ownsRun = () => mounted.current && run !== null
      && runRef.current?.id === run.id && epochRef.current === renderEpoch;
    return {
      run, presentation, preparing, renderEpoch,
      canReplay: !replayDisabledReason,
      replayDisabledReason,
      requestReplay,
      prepareStep: (id: OnboardingStepId) => ownsRun() ? prepare(id) : Promise.reject(onboardingAbortError()),
      finish: (reason: OnboardingExitReason) => { if (ownsRun()) finishRun(reason); },
      reportFailure: (error: unknown) => { if (ownsRun()) failRun(error); },
    };
  }, [run, presentation, preparing, renderEpoch, replayDisabledReason, requestReplay, prepare, finishRun, failRun]);
}
