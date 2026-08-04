import { ReactNode, useEffect } from "react";

interface ModalWindowProps {
  title: ReactNode;
  children: ReactNode;
  actions: ReactNode;
  onClose?: () => void;
  closeOnOverlayClick?: boolean;
  closeOnEsc?: boolean;
  className?: string;
}

// 模态窗口基元：全屏遮罩 + 居中窗框(title/body/actions)。
// 默认严格模态——遮罩点击与 ESC 均不关闭，由派生方显式开启。
export default function ModalWindow({
  title,
  children,
  actions,
  onClose,
  closeOnOverlayClick = false,
  closeOnEsc = false,
  className,
}: ModalWindowProps) {
  useEffect(() => {
    if (!closeOnEsc || !onClose) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closeOnEsc, onClose]);

  return (
    <div
      className="modal-overlay"
      onClick={closeOnOverlayClick ? onClose : undefined}
    >
      <div
        className={`modal-window${className ? ` ${className}` : ""}`}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-title">{title}</div>
        <div className="modal-body">{children}</div>
        <div className="modal-actions">{actions}</div>
      </div>
    </div>
  );
}