import { useMemo } from "react";
import { Joyride, STATUS, EVENTS, type Step } from "react-joyride";

interface OnboardingTourProps {
  run: boolean;
  onClose: () => void;
  isMobile: boolean;
  setSidebarCollapsed: React.Dispatch<React.SetStateAction<boolean>>;
  setDrawerOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setLlmDrawerOpen: React.Dispatch<React.SetStateAction<boolean>>;
  onPinSidebarChange: (pinned: boolean) => void;
  onPinHeaderChange: (pinned: boolean) => void;
}

export default function OnboardingTour({
  run,
  onClose,
  isMobile,
  setSidebarCollapsed,
  setDrawerOpen,
  setLlmDrawerOpen,
  onPinSidebarChange,
  onPinHeaderChange,
}: OnboardingTourProps) {
  const steps = useMemo<Step[]>(() => {
    const wait = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

    return [
      // 步骤 0：欢迎
      {
        target: "body",
        title: "欢迎使用 Evolve Agent",
        content: "Evolve Agent 是一个具备运行时自我代码进化能力的 AI。接下来带你快速了解界面布局。",
        placement: "center",
        hideOverlay: false,
        skipBeacon: true,
      },
      // 步骤 1：导航栏
      {
        target: '[data-tour="sidebar"]',
        title: "导航栏",
        content: "这里管理所有会话。可以搜索历史、新建会话、合并归档会话。",
        placement: "right",
        before: async () => {
          setSidebarCollapsed(false);
          await wait(300);
        },
        after: () => {
          if (isMobile) setSidebarCollapsed(true);
        },
      },
      // 步骤 2：顶部栏
      {
        target: '[data-tour="header"]',
        title: "顶部栏",
        content: "这里显示连接状态、审批模式切换（手动/脱手/YOLO）、Token 用量统计。",
        placement: "bottom",
      },
      // 步骤 3：输入栏
      {
        target: '[data-tour="input-bar"]',
        title: "输入栏",
        content: "在这里输入消息与 Agent 对话。支持文件上传、@提及、/命令、录音等。",
        placement: "top",
      },
      // 步骤 4：右侧触发条（仅展示，不打开抽屉）
      {
        target: '[data-tour="right-trigger-strip"]',
        title: "资源入口",
        content: "屏幕右缘的触发条可以打开资源抽屉、子会话面板、模型配置等。",
        placement: "left",
      },
      // 步骤 5：资源抽屉
      {
        target: '[data-tour="resource-drawer"]',
        title: "资源抽屉",
        content: "这里展示当前会话的图片、下载文件、后台任务和定时任务。",
        placement: "left",
        before: async () => {
          setDrawerOpen(true);
          await wait(300);
        },
        after: () => {
          setDrawerOpen(false);
        },
      },
      // 步骤 6：模型配置
      {
        target: '[data-tour="llm-drawer-panel"]',
        title: "模型配置",
        content: "在这里配置 LLM Profile，包括 API 密钥、模型选择、温度等参数。",
        placement: "left",
        before: async () => {
          setLlmDrawerOpen(true);
          await wait(300);
        },
        after: () => {
          setLlmDrawerOpen(false);
        },
      },
    ];
  }, [isMobile, setSidebarCollapsed, setDrawerOpen, setLlmDrawerOpen]);

  return (
    <Joyride
      continuous
      run={run}
      steps={steps}
      onEvent={(data) => {
        if (data.status === STATUS.FINISHED || data.status === STATUS.SKIPPED) {
          onPinSidebarChange(false);
          onPinHeaderChange(false);
          onClose();
        }
        // 步骤 1（导航栏）前后钉住/释放 Sidebar
        if (data.type === EVENTS.STEP_BEFORE && data.index === 1) {
          onPinSidebarChange(true);
        }
        if (data.type === EVENTS.STEP_AFTER && data.index === 1) {
          onPinSidebarChange(false);
        }
        // 步骤 2（顶部栏）前后钉住/释放 Header
        if (data.type === EVENTS.STEP_BEFORE && data.index === 2) {
          onPinHeaderChange(true);
        }
        if (data.type === EVENTS.STEP_AFTER && data.index === 2) {
          onPinHeaderChange(false);
        }
      }}
      options={{
        primaryColor: "#a78bfa",
        backgroundColor: "#131319",
        textColor: "#e6e6ec",
        arrowColor: "#131319",
        overlayColor: "rgba(0, 0, 0, 0.6)",
        zIndex: 10000,
        spotlightPadding: 8,
        spotlightRadius: 14,
        showProgress: true,
        width: 380,
        closeButtonAction: "skip",
        overlayClickAction: false,
        scrollDuration: 300,
        targetWaitTimeout: 2000,
      }}
      styles={{
        tooltip: {
          backgroundColor: "#131319",
          color: "#e6e6ec",
          borderRadius: "14px",
          fontSize: "14px",
          fontFamily: "inherit",
        },
        tooltipContainer: {
          backgroundColor: "#131319",
          color: "#e6e6ec",
        },
        tooltipContent: {
          backgroundColor: "#131319",
          color: "#e6e6ec",
          fontSize: "14px",
          lineHeight: 1.6,
        },
        tooltipTitle: {
          backgroundColor: "#131319",
          color: "#e6e6ec",
          fontSize: "16px",
          fontWeight: 600,
        },
        tooltipFooter: {
          backgroundColor: "#131319",
        },
        arrow: {
          color: "#131319",
          backgroundColor: "#131319",
        },
        buttonPrimary: {
          backgroundColor: "#a78bfa",
          color: "#ffffff",
          borderRadius: "8px",
          fontSize: "14px",
          padding: "8px 16px",
        },
        buttonBack: {
          backgroundColor: "#232330",
          color: "#e6e6ec",
          borderRadius: "8px",
          fontSize: "14px",
          padding: "8px 16px",
        },
        buttonSkip: {
          backgroundColor: "#1a1a22",
          color: "#9a9aa8",
          borderRadius: "8px",
          fontSize: "14px",
          padding: "8px 16px",
        },
        buttonClose: {
          color: "#9a9aa8",
        },
        overlay: {
          backgroundColor: "rgba(0, 0, 0, 0.6)",
        },
      }}
      locale={{
        back: "上一步",
        close: "关闭",
        last: "完成",
        next: "下一步",
        nextWithProgress: "下一步 ({current}/{total})",
        open: "打开",
        skip: "跳过",
      }}
    />
  );
}
