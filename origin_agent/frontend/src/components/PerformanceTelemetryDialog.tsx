import { useEffect, useState } from "react";
import { chatTelemetry } from "../features/chat/chatTelemetry";
import ModalWindow from "./primitives/ModalWindow";

export default function PerformanceTelemetryDialog({ onClose }: { onClose: () => void }) {
  const [snapshot, setSnapshot] = useState(() => chatTelemetry.snapshot());

  useEffect(() => chatTelemetry.subscribe(() => setSnapshot(chatTelemetry.snapshot())), []);

  return (
    <ModalWindow
      title="本地性能遥测"
      onClose={onClose}
      closeOnEsc
      closeOnOverlayClick
      className="telemetry-dialog"
      actions={(
        <>
          <button type="button" onClick={() => chatTelemetry.clear()}>清空</button>
          <button type="button" disabled={snapshot.eventCount === 0} onClick={() => chatTelemetry.exportReport()}>导出 JSON</button>
          <button type="button" onClick={onClose}>关闭</button>
        </>
      )}
    >
      <div className="telemetry-status-grid">
        <span>状态</span><strong>{snapshot.enabled ? "录制中" : "已关闭"}</strong>
        <span>开始时间</span><strong>{snapshot.startedAt || "—"}</strong>
        <span>事件数量</span><strong>{snapshot.eventCount}</strong>
        <span>长任务数量</span><strong>{snapshot.longTaskCount}</strong>
      </div>
      <p className="telemetry-note">仅在本地记录耗时、数量、逻辑范围和 DOM 统计，不记录消息正文、附件、工具参数或密钥。</p>
      <button
        type="button"
        className={snapshot.enabled ? "danger-btn" : "primary-btn"}
        onClick={() => snapshot.enabled ? chatTelemetry.stop() : chatTelemetry.start()}
      >
        {snapshot.enabled ? "停止录制" : "开始录制"}
      </button>
    </ModalWindow>
  );
}
