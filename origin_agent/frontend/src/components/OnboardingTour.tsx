import { useMemo } from "react";
import { Joyride, STATUS, EVENTS, type Step } from "react-joyride";
import type { TabId } from "../features/tabs/registry";

interface OnboardingTourProps {
  run: boolean;
  onClose: () => void;
  isMobile: boolean;
  setSidebarCollapsed: React.Dispatch<React.SetStateAction<boolean>>;
  switchTab: (id: TabId) => void;
  onPinSidebarChange: (pinned: boolean) => void;
}

export default function OnboardingTour({
  run,
  onClose,
  isMobile,
  setSidebarCollapsed,
  switchTab,
  onPinSidebarChange,
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
        content: "这里显示会话标题、待用模型、上下文进度和连接健康状态。命令菜单与审批模式切换位于右侧 Tab 栏底部。",
        placement: "bottom",
      },
      // 步骤 3：输入栏
      {
        target: '[data-tour="input-bar"]',
        title: "输入栏",
        content: "在这里输入消息与 Agent 对话。支持文件上传、@提及、/命令、录音等。",
        placement: "top",
      },
      // 步骤 4：右侧 Tab 栏（仅展示，不切换）
      {
        target: '[data-tour="tab-rail"]',
        title: "右侧 Tab 栏",
        content: "屏幕右缘的右侧 Tab 栏切换主界面视图：聊天、资源、子会话、会话网页、模型配置、动态沙盒空间。",
        placement: "left",
      },
      // 步骤 5：右侧 Tab 栏底部控制
      {
        target: '[data-tour="tab-rail-footer"]',
        title: "全局控制",
        content: "右侧 Tab 栏底部固定显示审批模式三态切换和命令菜单，不会随 Tab 图标滚动。",
        placement: "left",
      },
      // 步骤 6：资源 Tab
      {
        target: '[data-tour="resources-tab"]',
        title: "资源 / 任务",
        content: "这里展示当前会话的图片、下载文件、Shell 会话和定时任务。",
        placement: "left",
        before: async () => {
          switchTab("resources");
          await wait(300);
        },
        after: () => {
          switchTab("chat");
        },
      },
      // 步骤 7：模型配置
      {
        target: '[data-tour="llm-tab"]',
        title: "模型配置",
        content: "模型配置页按客户端和端点管理连接、参数；全局配置引用页选择审批与元数据模型。当前会话的待用模型从顶部栏切换。",
        placement: "left",
        before: async () => {
          switchTab("llm");
          await wait(300);
        },
        after: () => {
          switchTab("chat");
        },
      },
    ];
  }, [isMobile, setSidebarCollapsed, switchTab]);

  return (
    <Joyride
      continuous
      run={run}
      steps={steps}
      onEvent={(data) => {
        if (data.status === STATUS.FINISHED || data.status === STATUS.SKIPPED) {
          onPinSidebarChange(false);
          onClose();
        }
        // 步骤 1（导航栏）前后钉住/释放 Sidebar
        if (data.type === EVENTS.STEP_BEFORE && data.index === 1) {
          onPinSidebarChange(true);
        }
        if (data.type === EVENTS.STEP_AFTER && data.index === 1) {
          onPinSidebarChange(false);
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
