import { useCallback, useRef, useState } from "react";
import { WSMessage } from "../types";
import { generateUUID } from "../utils";
import { STORAGE_KEYS } from "../constants/storage";
import { WS_CLOSE_SESSION_DELETED, WS_IN, WS_OUT } from "../constants/ws";
import { TIMING } from "../constants/timing";

export interface WebSocketConnectionHandlers {
  onOpen?: () => void;
  onMessage?: (msg: WSMessage) => void;
  onClose?: () => void;
  onSessionDeleted?: () => void;
}

export interface WebSocketConnection {
  wsRef: React.RefObject<WebSocket | null>;
  status: string;
  setStatus: React.Dispatch<React.SetStateAction<string>>;
  connect: (resumeSid?: string) => Promise<void>;
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
  sessionLocked: boolean;
  retryConnect: () => void;
}

export function useWebSocketConnection(): WebSocketConnection {
  const [status, setStatus] = useState("connecting...");
  const [recvTick, setRecvTick] = useState(0);
  const [sessionLocked, setSessionLocked] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const keepaliveRef = useRef<ReturnType<typeof setInterval>>();
  const manualRef = useRef(false);
  const lastRecvAtRef = useRef<number>(Date.now());
  const lastPongAtRef = useRef<number>(Date.now());
  const handlersRef = useRef<WebSocketConnectionHandlers>({});
  const wasOpenRef = useRef(false);
  const lastSidRef = useRef<string | undefined>(undefined);
  const connectIdRef = useRef(0);

  const setHandlers = useCallback((handlers: WebSocketConnectionHandlers) => {
    handlersRef.current = handlers;
  }, []);

  const send = useCallback((payload: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload));
    }
  }, []);

  const getOrCreateConnToken = useCallback((): string => {
    let token = sessionStorage.getItem(STORAGE_KEYS.CONN_TOKEN);
    if (!token) {
      token = generateUUID();
      sessionStorage.setItem(STORAGE_KEYS.CONN_TOKEN, token);
    }
    return token;
  }, []);

  const disconnect = useCallback(() => {
    manualRef.current = true;
    connectIdRef.current += 1; // Invalidate in-flight async connect pre-check
    if (keepaliveRef.current) clearInterval(keepaliveRef.current);
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }
    clearTimeout(timerRef.current);
  }, []);

  const connect = useCallback(async (resumeSid?: string) => {
    const myId = ++connectIdRef.current;
    const urlSid = new URLSearchParams(window.location.search).get("session") ?? undefined;
    // lastSid 是最终用于连接的 sid，按优先级：显式传入 > URL 参数 > localStorage 残留
    const lastSid = (resumeSid || undefined) ?? urlSid ?? localStorage.getItem(STORAGE_KEYS.SESSION_ID) ?? "";
    // preCheckSid 只覆盖用户显式指定的目标；localStorage 残留由握手失败后的状态查询确认。
    const preCheckSid = (resumeSid || undefined) ?? urlSid;
    const token = getOrCreateConnToken();

    const notifySessionDeleted = () => {
      if (myId !== connectIdRef.current) return;
      manualRef.current = true;
      reconnectRef.current = 0;
      clearTimeout(timerRef.current);
      setSessionLocked(false);
      setStatus("会话已删除");
      handlersRef.current.onSessionDeleted?.();
    };

    // Pre-check: only when user explicitly targets an existing session
    if (preCheckSid) {
      try {
        const resp = await fetch(
          `/api/sessions/${preCheckSid}/status?conn_token=${encodeURIComponent(token)}`
        ).then((r) => r.json());
        if (myId !== connectIdRef.current) return; // Stale request
        if (resp.exists === false) {
          notifySessionDeleted();
          return;
        }
        if (resp.occupied) {
          setSessionLocked(true);
          setStatus("会话已被占用");
          lastSidRef.current = preCheckSid;
          return;
        }
      } catch {
        // Pre-check failed (network error/server down) → continue to connect
      }
    }

    if (myId !== connectIdRef.current) return; // Stale request
    setSessionLocked(false);
    wasOpenRef.current = false;
    lastSidRef.current = lastSid || undefined;  // Full sid (incl. localStorage fallback) for handshake rejection detection

    const qs = lastSid
      ? `?resume=${lastSid}&conn_token=${encodeURIComponent(token)}`
      : `?conn_token=${encodeURIComponent(token)}`;
    const ws = new WebSocket(`ws://${location.host}/ws/chat${qs}`);
    wsRef.current = ws;

    ws.onopen = () => {
      wasOpenRef.current = true;
      reconnectRef.current = 0;
      manualRef.current = false;
      setStatus("已连接");
      if (keepaliveRef.current) clearInterval(keepaliveRef.current);
      keepaliveRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: WS_OUT.PING }));
        }
      }, TIMING.WS_KEEPALIVE);
      handlersRef.current.onOpen?.();
    };

    ws.onclose = (event) => {
      if (keepaliveRef.current) clearInterval(keepaliveRef.current);

      if (event.code === WS_CLOSE_SESSION_DELETED) {
        notifySessionDeleted();
        return;
      }

      // Handshake rejection detection: onopen never fired. Browsers may report
      // a pre-accept rejection as 1006, so the HTTP status response is authoritative.
      if (!wasOpenRef.current && lastSidRef.current) {
        const sid = lastSidRef.current;
        fetch(`/api/sessions/${sid}/status?conn_token=${encodeURIComponent(token)}`)
          .then((r) => r.json())
          .then((data) => {
            if (myId !== connectIdRef.current) return;
            if (data.exists === false) {
              notifySessionDeleted();
            } else if (data.occupied) {
              setSessionLocked(true);
              setStatus("会话已被占用");
            } else {
              setStatus("连接失败");
            }
          })
          .catch(() => {
            if (myId !== connectIdRef.current) return;
            setStatus("连接失败");
          });
        return; // Don't trigger onClose handler or auto-reconnect
      }

      setStatus("已断开");
      handlersRef.current.onClose?.();
      if (manualRef.current) return;
      if (reconnectRef.current >= TIMING.WS_MAX_RECONNECT_TRIES) {
        setStatus("连接失败 — 已达到最大重试次数");
        return;
      }
      const delay = Math.min(TIMING.WS_RECONNECT_BASE * Math.pow(2, reconnectRef.current), TIMING.WS_MAX_RECONNECT_DELAY);
      reconnectRef.current += 1;
      setStatus(`重连中 (${(delay / 1000).toFixed(0)}s)...`);
      timerRef.current = setTimeout(() => connect(lastSid), delay);
    };

    ws.onmessage = (e) => {
      if (myId !== connectIdRef.current || wsRef.current !== ws) return;
      const msg: WSMessage = JSON.parse(e.data);
      const now = Date.now();
      lastRecvAtRef.current = now;
      setRecvTick((v) => v + 1);
      const payloadLen = typeof e.data === "string" ? e.data.length : 0;
      console.debug(`[ws recv] type=${msg.type} len=${payloadLen} at=${now}`);
      if (msg.type === WS_IN.PONG) {
        lastPongAtRef.current = now;
      }
      handlersRef.current.onMessage?.(msg);
    };
  }, [getOrCreateConnToken]);

  const retryConnect = useCallback(() => {
    setSessionLocked(false);
    connect(lastSidRef.current);
  }, [connect]);

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
    sessionLocked,
    retryConnect,
  };
}