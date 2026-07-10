import { useCallback, useRef, useState } from "react";
import { WSMessage } from "../types";

export interface WebSocketConnectionHandlers {
  onOpen?: () => void;
  onMessage?: (msg: WSMessage) => void;
  onClose?: () => void;
}

export interface WebSocketConnection {
  wsRef: React.RefObject<WebSocket | null>;
  status: string;
  setStatus: React.Dispatch<React.SetStateAction<string>>;
  connect: (resumeSid?: string) => void;
  send: (payload: unknown) => void;
  disconnect: () => void;
  setHandlers: (handlers: WebSocketConnectionHandlers) => void;
  manualRef: React.RefObject<boolean>;
  reconnectRef: React.RefObject<number>;
  timerRef: React.RefObject<ReturnType<typeof setTimeout> | undefined>;
  keepaliveRef: React.RefObject<ReturnType<typeof setInterval> | undefined>;
  lastRecvAtRef: React.RefObject<number>;
  lastPongAtRef: React.RefObject<number>;
  recvTick: number;
}

export function useWebSocketConnection(): WebSocketConnection {
  const [status, setStatus] = useState("connecting...");
  const [recvTick, setRecvTick] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const keepaliveRef = useRef<ReturnType<typeof setInterval>>();
  const manualRef = useRef(false);
  const lastRecvAtRef = useRef<number>(Date.now());
  const lastPongAtRef = useRef<number>(Date.now());
  const handlersRef = useRef<WebSocketConnectionHandlers>({});

  const setHandlers = useCallback((handlers: WebSocketConnectionHandlers) => {
    handlersRef.current = handlers;
  }, []);

  const send = useCallback((payload: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload));
    }
  }, []);

  const disconnect = useCallback(() => {
    manualRef.current = true;
    if (keepaliveRef.current) clearInterval(keepaliveRef.current);
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }
    clearTimeout(timerRef.current);
  }, []);

  const connect = useCallback((resumeSid?: string) => {
    const lastSid = resumeSid ?? localStorage.getItem("evolve_session_id") ?? "";
    const qs = lastSid ? `?resume=${lastSid}` : "";
    const ws = new WebSocket(`ws://${location.host}/ws/chat${qs}`);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectRef.current = 0;
      manualRef.current = false;
      setStatus("已连接");
      if (keepaliveRef.current) clearInterval(keepaliveRef.current);
      keepaliveRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }));
        }
      }, 20000);
      handlersRef.current.onOpen?.();
    };

    ws.onclose = () => {
      if (keepaliveRef.current) clearInterval(keepaliveRef.current);
      setStatus("已断开");
      handlersRef.current.onClose?.();
      if (manualRef.current) return;
      if (reconnectRef.current >= 10) {
        setStatus("连接失败 — 已达到最大重试次数");
        return;
      }
      const delay = Math.min(1000 * Math.pow(2, reconnectRef.current), 30000);
      reconnectRef.current += 1;
      setStatus(`重连中 (${(delay / 1000).toFixed(0)}s)...`);
      timerRef.current = setTimeout(() => connect(lastSid), delay);
    };

    ws.onmessage = (e) => {
      const msg: WSMessage = JSON.parse(e.data);
      const now = Date.now();
      lastRecvAtRef.current = now;
      setRecvTick((v) => v + 1);
      const payloadLen = typeof e.data === "string" ? e.data.length : 0;
      console.debug(`[ws recv] type=${msg.type} len=${payloadLen} at=${now}`);
      if (msg.type === "pong") {
        lastPongAtRef.current = now;
      }
      handlersRef.current.onMessage?.(msg);
    };
  }, []);

  return {
    wsRef,
    status,
    setStatus,
    connect,
    send,
    disconnect,
    setHandlers,
    manualRef,
    reconnectRef,
    timerRef,
    keepaliveRef,
    lastRecvAtRef,
    lastPongAtRef,
    recvTick,
  };
}