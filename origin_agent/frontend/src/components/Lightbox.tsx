import { useEffect, useRef } from "react";
import {
  TransformWrapper,
  TransformComponent,
  useControls,
} from "react-zoom-pan-pinch";
import "../styles/lightbox.css";

interface LightboxProps {
  src: string;
  onClose: () => void;
}

const DRAG_THRESHOLD = 5;

function Toolbar({ onClose }: { onClose: () => void }) {
  const { zoomIn, zoomOut, resetTransform } = useControls();

  return (
    <div className="lightbox-toolbar" onClick={(e) => e.stopPropagation()}>
      <button
        className="lightbox-btn"
        onClick={() => zoomIn(0.2)}
        data-tooltip="放大"
      >
        +
      </button>
      <button
        className="lightbox-btn"
        onClick={() => zoomOut(0.2)}
        data-tooltip="缩小"
      >
        −
      </button>
      <button
        className="lightbox-btn"
        onClick={() => resetTransform()}
        data-tooltip="重置"
      >
        ⟲
      </button>
      <button
        className="lightbox-btn lightbox-btn-close"
        onClick={onClose}
        data-tooltip="关闭"
      >
        ×
      </button>
    </div>
  );
}

export default function Lightbox({ src, onClose }: LightboxProps) {
  const dragStartRef = useRef<{ x: number; y: number; moved: boolean } | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    dragStartRef.current = { x: e.clientX, y: e.clientY, moved: false };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!dragStartRef.current) return;
    const dx = Math.abs(e.clientX - dragStartRef.current.x);
    const dy = Math.abs(e.clientY - dragStartRef.current.y);
    if (dx > DRAG_THRESHOLD || dy > DRAG_THRESHOLD) {
      dragStartRef.current.moved = true;
    }
  };

  const handleMouseUp = () => {
    const start = dragStartRef.current;
    dragStartRef.current = null;
    if (!start) return;
    if (start.moved) return;
    onClose();
  };

  return (
    <div
      className="lightbox-backdrop"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
    >
      <TransformWrapper
        initialScale={1}
        minScale={0.5}
        maxScale={5}
        centerOnInit
        limitToBounds={false}
        panning={{ velocityDisabled: true }}
        wheel={{ step: 0.2 }}
        doubleClick={{ mode: "toggle" }}
      >
        {() => (
          <>
            <Toolbar onClose={onClose} />
            <TransformComponent
              wrapperClass="lightbox-transform-wrapper"
              contentClass="lightbox-transform-content"
            >
              <img
                src={src}
                className="lightbox-img"
                onClick={(e) => e.stopPropagation()}
                draggable={false}
                alt="预览"
              />
            </TransformComponent>
          </>
        )}
      </TransformWrapper>
    </div>
  );
}
