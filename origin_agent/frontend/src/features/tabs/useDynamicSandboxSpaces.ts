import { useCallback, useEffect, useRef, useState } from "react";
import type { DynamicSandboxSpaceWithAvailability } from "../../types";
import { listDynamicSandboxSpaces } from "../../services/dynamicSandboxSpacesApi";

export interface UseDynamicSandboxSpacesState {
  spaces: DynamicSandboxSpaceWithAvailability[] | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<DynamicSandboxSpaceWithAvailability[] | null>;
}

/**
 * 动态沙盒空间列表的唯一持有者：只提供只读列表与手动 refresh，不自动读取。
 * 激活读取仍由 SandboxTab 的 activation effect 驱动；代际与卸载取消防止旧响应覆盖。
 */
export function useDynamicSandboxSpaces(): UseDynamicSandboxSpacesState {
  const [spaces, setSpaces] = useState<DynamicSandboxSpaceWithAvailability[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generationRef = useRef(0);
  const requestRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async (): Promise<DynamicSandboxSpaceWithAvailability[] | null> => {
    const generation = ++generationRef.current;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    try {
      const data = await listDynamicSandboxSpaces(controller.signal);
      if (generationRef.current !== generation) return null;
      setSpaces(data.spaces);
      setError(null);
      return data.spaces;
    } catch (failure) {
      if (generationRef.current !== generation) return null;
      const aborted = failure instanceof DOMException && failure.name === "AbortError";
      if (aborted) return null;
      setError(failure instanceof Error ? failure.message : String(failure));
      return null;
    } finally {
      if (generationRef.current === generation) {
        setLoading(false);
        requestRef.current = null;
      }
    }
  }, []);

  useEffect(() => () => {
    generationRef.current++;
    requestRef.current?.abort();
    requestRef.current = null;
  }, []);

  return { spaces, loading, error, refresh };
}