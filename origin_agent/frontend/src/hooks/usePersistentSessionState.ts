import { useCallback, useEffect, useRef, useState } from "react";

/**
 * 按会话隔离的持久化 hook。
 * 底层存储为 Record<string, T> 的 JSON 序列化，每个 sessionId 对应一个独立条目。
 * setValue 仅更新当前 sessionId 的条目。
 */
export function usePersistentSessionState<T>(
  key: string,
  sessionId: string,
  defaultValue: T,
): [T, (value: T | ((prev: T) => T)) => void] {
  const defaultValueRef = useRef(defaultValue);
  defaultValueRef.current = defaultValue;

  const [sessionMap, setSessionMap] = useState<Record<string, T>>(() => {
    try {
      const stored = localStorage.getItem(key);
      if (stored === null) return {};
      return JSON.parse(stored) as Record<string, T>;
    } catch {
      return {};
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(sessionMap));
    } catch {
      // localStorage 不可用或 quota exceeded 时静默失败
    }
  }, [key, sessionMap]);

  const value = sessionId in sessionMap ? sessionMap[sessionId] : defaultValueRef.current;

  const setValue = useCallback(
    (next: T | ((prev: T) => T)) => {
      setSessionMap((prev) => {
        const current = sessionId in prev ? prev[sessionId] : defaultValueRef.current;
        const resolved = typeof next === "function" ? (next as (p: T) => T)(current) : next;
        return { ...prev, [sessionId]: resolved };
      });
    },
    [sessionId],
  );

  return [value, setValue];
}