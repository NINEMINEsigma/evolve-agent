import React, { useEffect, useImperativeHandle, useRef, useState, type ClipboardEvent, type KeyboardEvent } from "react";
import type { PendingImage } from "../hooks/useWebSocket";

interface RichInputProps {
  value: string;
  onChange: (html: string, text: string) => void;
  onSend: () => void;
  onPasteImage: (file: File) => Promise<{ id: string; dataUrl: string } | null>;
  onRemoveImage: (id: string) => void;
  pendingImages: PendingImage[];
  disabled?: boolean;
  placeholder?: string;
}

const RichInput = React.forwardRef<HTMLDivElement, RichInputProps>(function RichInput({
  value,
  onChange,
  onSend,
  onPasteImage,
  onRemoveImage,
  pendingImages,
  disabled,
  placeholder,
}, ref) {
  const innerRef = useRef<HTMLDivElement>(null);
  useImperativeHandle(ref, () => innerRef.current!);
  const divRef = innerRef;
  const [isEmpty, setIsEmpty] = useState(!value);

  useEffect(() => {
    const el = divRef.current;
    if (!el) return;
    // 仅在受控 value 改变且与当前 innerHTML 不一致时同步，避免编辑时丢光标
    const currentText = el.innerText || "";
    if (value !== el.innerHTML && value !== currentText) {
      el.innerHTML = value;
      setIsEmpty(!el.innerText?.trim() && !el.querySelector(".input-inline-image"));
      autoResize();
    }
  }, [value]);

  useEffect(() => {
    // 当 pendingImages 变化时，移除已不存在的图片节点
    const el = divRef.current;
    if (!el) return;
    const ids = new Set(pendingImages.map((img) => img.id));
    el.querySelectorAll<HTMLSpanElement>(".input-inline-image").forEach((node) => {
      if (!ids.has(node.dataset.imageId || "")) {
        node.remove();
      }
    });
    setIsEmpty(!el.innerText?.trim() && !el.querySelector(".input-inline-image"));
  }, [pendingImages]);

  const notifyChange = () => {
    const el = divRef.current;
    if (!el) return;
    const html = el.innerHTML;
    const text = el.innerText || "";
    setIsEmpty(!text.trim() && !el.querySelector(".input-inline-image"));
    onChange(html, text);
  };

  const handleInput = () => {
    notifyChange();
    autoResize();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  const autoResize = () => {
    const el = divRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  const insertNodeAtCursor = (node: Node) => {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) {
      divRef.current?.appendChild(node);
      return true;
    }
    const range = sel.getRangeAt(0);
    if (!divRef.current?.contains(range.commonAncestorContainer)) {
      divRef.current?.appendChild(node);
      return true;
    }
    range.deleteContents();
    range.insertNode(node);
    range.setStartAfter(node);
    range.setEndAfter(node);
    sel.removeAllRanges();
    sel.addRange(range);
    return true;
  };

  const handlePaste = async (e: ClipboardEvent<HTMLDivElement>) => {
    const items = e.clipboardData?.files;
    if (!items || items.length === 0) return;
    const imageFiles = Array.from(items).filter((f) => f.type.startsWith("image/"));
    if (imageFiles.length === 0) return;
    e.preventDefault();

    for (const file of imageFiles) {
      const result = await onPasteImage(file);
      if (!result) continue;
      const { id, dataUrl } = result;
      const wrapper = document.createElement("span");
      wrapper.className = "input-inline-image";
      wrapper.contentEditable = "false";
      wrapper.dataset.imageId = id;
      wrapper.innerHTML = `<img src="${dataUrl}" alt="" /><button type="button" class="input-inline-remove">×</button>`;
      wrapper.querySelector(".input-inline-remove")?.addEventListener("click", () => {
        onRemoveImage(id);
        wrapper.remove();
        notifyChange();
        autoResize();
      });
      insertNodeAtCursor(wrapper);
    }
    notifyChange();
    autoResize();
  };

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    const removeBtn = target.closest(".input-inline-remove") as HTMLButtonElement | null;
    if (!removeBtn) return;
    const wrapper = removeBtn.closest(".input-inline-image") as HTMLSpanElement | null;
    if (!wrapper) return;
    const id = wrapper.dataset.imageId;
    if (id) onRemoveImage(id);
    wrapper.remove();
    e.preventDefault();
    notifyChange();
    autoResize();
  };

  return (
    <div className="rich-input-wrapper">
      <div
        ref={divRef}
        className="rich-input"
        contentEditable={!disabled}
        onInput={handleInput}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        onClick={handleClick}
        onBlur={notifyChange}
        data-placeholder={placeholder}
        suppressContentEditableWarning
      />
      {isEmpty && placeholder && (
        <div className="rich-input-placeholder">{placeholder}</div>
      )}
    </div>
  );
});

export default RichInput;
