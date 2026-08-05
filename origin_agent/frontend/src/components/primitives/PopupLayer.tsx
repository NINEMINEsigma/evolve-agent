import { CSSProperties, MutableRefObject, ReactNode, Ref, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface PopupLayerProps {
  children: ReactNode;                  // 浮层内容（item 结构派生方自由渲染）
  position: { x: number; y: number };   // 期望坐标（视口系）
  onClose?: () => void;                 // 缺省时所有关闭交互不生效
  closeOnOutsideClick?: boolean;        // 默认 true（宽松）；可显式 false
  closeOnEsc?: boolean;                 // 默认 true（宽松）；可显式 false
  className?: string;                   // 修饰类（.context-menu / .mention-menu / .agentspace-context-menu）
  style?: CSSProperties;                // 透传到容器（MentionMenu 的 translateY 用）；不得传 left/top（定位归基元）
  containerRef?: Ref<HTMLDivElement>;   // 容器引用通道（React 18 无 ref-as-prop，用命名 prop）
}

// 弹出浮层基元：fixed 定位 + 硬性防越界 + portal 到 body + 默认宽松关闭。
// 与 ModalWindow（模态严格）对称：浮层默认外部点击 / ESC 关闭，可分别显式关闭任一。
export default function PopupLayer({
  children,
  position,
  onClose,
  closeOnOutsideClick = true,
  closeOnEsc = true,
  className,
  style,
  containerRef,
}: PopupLayerProps) {
  // React 18 的 useRef<HTMLDivElement>(null) 命中 RefObject 重载（current readonly），
  // 显式带 null 联合使 current 可写
  const elRef = useRef<HTMLDivElement | null>(null);
  const [adjusted, setAdjusted] = useState(position);

  // 防越界（硬性，不可关）：以渲染后实际 rect（含派生 transform 位移）为基准夹逼视口，
  // 平移量 dx/dy 应用到 left/top，对派生方 transform 透明。仅在 position 变化时重算
  // （菜单打开期间内容尺寸变化不重夹逼——与现状 ChatContextMenu 同局限，非回归）。
  useLayoutEffect(() => {
    const el = elRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const margin = 8;
    let dx = 0;
    let dy = 0;
    if (rect.left < margin) dx = margin - rect.left;
    else if (rect.right > window.innerWidth - margin) dx = window.innerWidth - margin - rect.right;
    if (rect.top < margin) dy = margin - rect.top;
    else if (rect.bottom > window.innerHeight - margin) dy = window.innerHeight - margin - rect.bottom;
    const nx = position.x + dx;
    const ny = position.y + dy;
    setAdjusted((prev) => (prev.x === nx && prev.y === ny ? prev : { x: nx, y: ny }));
  }, [position.x, position.y]);

  // 关闭（默认宽松）：onClose 存在时默认外部点击 + ESC，卸载时确定性移除
  useEffect(() => {
    if (!onClose) return;
    const onMouseDown = (e: MouseEvent) => {
      if (elRef.current && !elRef.current.contains(e.target as Node)) onClose();
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (closeOnOutsideClick) document.addEventListener("mousedown", onMouseDown);
    if (closeOnEsc) document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose, closeOnOutsideClick, closeOnEsc]);

  return createPortal(
    <div
      ref={(node) => {
        elRef.current = node;
        if (typeof containerRef === "function") containerRef(node);
        // React 18 的 RefObject.current 为 readonly，需断言后才能赋值
        else if (containerRef) (containerRef as MutableRefObject<HTMLDivElement | null>).current = node;
      }}
      className={`popup-layer${className ? ` ${className}` : ""}`}
      style={{ left: adjusted.x, top: adjusted.y, ...style }}
    >
      {children}
    </div>,
    document.body,
  );
}