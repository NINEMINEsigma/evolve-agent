import { TIMING } from "../constants/timing";
import { useConnectionDiagnostics } from "../context/ConnectionDiagnosticsContext";
import { useChatRuntimeStore } from "../features/chat/chatRuntimeStore";

export type ConnectionHealth = "healthy" | "warning" | "error";

export function resolveConnectionHealth(
  status: string,
  recvStall: number,
  pongStall: number,
  recvStallThreshold: number,
): ConnectionHealth {
  if (
    status === "已断开"
    || status === "连接失败 — 已达到最大重试次数"
    || recvStall >= recvStallThreshold
  ) {
    return "error";
  }
  if (status.startsWith("重连中") || pongStall >= TIMING.PONG_STALL || status !== "已连接") {
    return "warning";
  }
  return "healthy";
}

function receiveLabel(recvStall: number, threshold: number): string {
  return recvStall >= threshold
    ? `接收停滞（${Math.floor(recvStall / 1000)}s）`
    : "接收正常";
}

function heartbeatLabel(pongStall: number): string {
  return pongStall >= TIMING.PONG_STALL
    ? `心跳异常（${Math.floor(pongStall / 1000)}s）`
    : "心跳正常";
}

export default function ConnectionStatusLight({ status }: { status: string }) {
  const { pendingConfirm, ignoreStaleRef, lastRecvAtRef, lastPongAtRef, recvTick, now } =
    useConnectionDiagnostics();
  const waiting = useChatRuntimeStore((state) => state.processing);
  const currentStreamId = useChatRuntimeStore((state) => state.currentStreamId);

  const lastRecv = lastRecvAtRef?.current ?? now;
  const lastPong = lastPongAtRef?.current ?? now;
  const recvStall = now - lastRecv;
  const pongStall = now - lastPong;
  const active = waiting || !!currentStreamId;
  const recvStallThreshold = active ? TIMING.RECV_STALL_ACTIVE : TIMING.RECV_STALL_INACTIVE;
  const health = resolveConnectionHealth(status, recvStall, pongStall, recvStallThreshold);
  const tooltip = [
    `连接：${status || "未知"}`,
    receiveLabel(recvStall, recvStallThreshold),
    heartbeatLabel(pongStall),
    waiting ? "处理中" : "空闲",
    currentStreamId ? "流式输出中" : "无活动流",
    pendingConfirm ? "待审批" : "无待审批",
    ignoreStaleRef?.current ? "忽略旧消息：是" : "忽略旧消息：否",
  ].join("\n");

  return (
    <span
      key={recvTick}
      className={`connection-status-light connection-status-light--${health}`}
      data-tooltip={tooltip}
      role="img"
      aria-label={`连接健康状态：${health === "healthy" ? "正常" : health === "warning" ? "警告" : "异常"}`}
    />
  );
}
