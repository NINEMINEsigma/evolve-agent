import { useEffect, useRef, useState } from "react";

interface PersistentStateOptions<T> {
  serialize?: (value: T) => string;
  deserialize?: (stored: string) => T;
}

/**
 * 全局持久化 hook，API 与 useState 对齐。
 * 值变化时自动写入 localStorage，初始化时从 localStorage 恢复。
 */
export function usePersistentState<T>(
  key: string,
  defaultValue: T,
  options?: PersistentStateOptions<T>,
): [T, React.Dispatch<React.SetStateAction<T>>] {
  const serialize = options?.serialize ?? ((v: T) => JSON.stringify(v));
  const deserialize = options?.deserialize ?? ((s: string) => JSON.parse(s) as T);

  const serializeRef = useRef(serialize);
  const deserializeRef = useRef(deserialize);
  serializeRef.current = serialize;
  deserializeRef.current = deserialize;

  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(key);
      if (stored === null) return defaultValue;
      return deserializeRef.current(stored);
    } catch {
      return defaultValue;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, serializeRef.current(value));
    } catch {
      // localStorage 不可用（隐私模式 / quota exceeded）时静默失败
    }
  }, [key, value]);

  return [value, setValue];
}