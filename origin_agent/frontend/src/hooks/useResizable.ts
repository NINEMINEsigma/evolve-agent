import { useCallback, useRef, useState } from "react";

interface UseResizableOptions {
  width: number;
  setWidth: React.Dispatch<React.SetStateAction<number>>;
  min: number;
  max: number;
  /** "left" = 面板在左侧，向右拖拽增大宽度；"right" = 面板在右侧，向左拖拽增大宽度 */
  direction: "left" | "right";
}

interface UseResizableResult {
  onPointerDown: (e: React.PointerEvent<HTMLElement>) => void;
  isResizing: boolean;
}

/**
 * 通用拖拽调整宽度 hook。
 * 通过 pointer 事件监听拖拽，在 min/max 范围内更新宽度。
 */
export function useResizable({
  width,
  setWidth,
  min,
  max,
  direction,
}: UseResizableOptions): UseResizableResult {
  const [isResizing, setIsResizing] = useState(false);
  const widthRef = useRef(width);
  widthRef.current = width;

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      e.preventDefault();
      setIsResizing(true);
      const startX = e.clientX;
      const startWidth = widthRef.current;

      const handleMove = (ev: PointerEvent) => {
        const delta =
          direction === "right"
            ? startX - ev.clientX
            : ev.clientX - startX;
        const newWidth = Math.max(min, Math.min(max, startWidth + delta));
        setWidth(newWidth);
      };

      const handleUp = () => {
        setIsResizing(false);
        window.removeEventListener("pointermove", handleMove);
        window.removeEventListener("pointerup", handleUp);
      };

      window.addEventListener("pointermove", handleMove);
      window.addEventListener("pointerup", handleUp);
    },
    [direction, min, max, setWidth],
  );

  return { onPointerDown, isResizing };
}