import { useEffect, useRef, useState, useCallback } from "react";
import mermaid from "mermaid";
import {
  TransformWrapper,
  TransformComponent,
  useControls,
} from "react-zoom-pan-pinch";

interface MermaidRendererProps {
  definition: string;
}

let mermaidInitialized = false;

function ensureMermaidInitialized() {
  if (mermaidInitialized) return;
  const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  mermaid.initialize({
    startOnLoad: false,
    theme: dark ? "dark" : "default",
    securityLevel: "loose",
    suppressErrorRendering: true,
  });
  mermaidInitialized = true;
}

function LightboxToolbar({ onClose }: { onClose: () => void }) {
  const { zoomIn, zoomOut, resetTransform } = useControls();
  return (
    <div className="lightbox-toolbar" onClick={(e) => e.stopPropagation()}>
      <button className="lightbox-btn" onClick={() => zoomIn(0.2)}>+</button>
      <button className="lightbox-btn" onClick={() => zoomOut(0.2)}>−</button>
      <button className="lightbox-btn" onClick={() => resetTransform()}>⟲</button>
      <button className="lightbox-btn lightbox-btn-close" onClick={onClose}>×</button>
    </div>
  );
}

function MermaidLightbox({ svg, onClose }: { svg: string; onClose: () => void }) {
  const backdropRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      ref={backdropRef}
      className="lightbox-backdrop"
      onClick={(e) => { if (e.target === backdropRef.current) onClose(); }}
    >
      <TransformWrapper
        initialScale={1}
        minScale={0.3}
        maxScale={8}
        centerOnInit
        limitToBounds={false}
        panning={{ velocityDisabled: true }}
        wheel={{ step: 0.2 }}
        doubleClick={{ mode: "toggle" }}
      >
        {() => (
          <>
            <LightboxToolbar onClose={onClose} />
            <TransformComponent
              wrapperClass="lightbox-transform-wrapper"
              contentClass="lightbox-transform-content"
            >
              <div
                className="mermaid-lightbox-svg"
                dangerouslySetInnerHTML={{ __html: svg }}
              />
            </TransformComponent>
          </>
        )}
      </TransformWrapper>
    </div>
  );
}

export default function MermaidRenderer({ definition }: MermaidRendererProps) {
  const [svgString, setSvgString] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!definition.trim()) return;
    let cancelled = false;
    ensureMermaidInitialized();

    const render = async () => {
      try {
        const id = `m-${Math.random().toString(36).slice(2, 9)}`;
        const result = await mermaid.render(id, definition.trim());
        if (cancelled) return;
        setSvgString(result.svg);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      }
    };

    render();
    return () => { cancelled = true; };
  }, [definition]);

  const handleClick = useCallback(() => {
    setExpanded(true);
  }, []);

  const handleClose = useCallback(() => {
    setExpanded(false);
  }, []);

  if (error) {
    return (
      <pre className="mermaid-error">
        Mermaid failed: {error}
      </pre>
    );
  }

  if (!svgString) {
    return <pre className="mermaid-loading">Rendering…</pre>;
  }

  return (
    <>
      <div
        ref={containerRef}
        className="mermaid-svg-container"
        onClick={handleClick}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter") handleClick(); }}
        dangerouslySetInnerHTML={{ __html: svgString }}
      />
      {expanded && (
        <MermaidLightbox svg={svgString} onClose={handleClose} />
      )}
    </>
  );
}