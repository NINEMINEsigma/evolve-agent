import { useState, useCallback, useRef } from "react";
import { ChatMessage, ContentBlock, MessageContent, PendingImage } from "../types";
import { generateUUID, escapeHtml, contentBlocksToHtml, extractContentBlocks } from "../utils";
import RichInput from "./RichInput";
import { DIMENSIONS } from "../constants/dimensions";

interface MessageEditorProps {
  message: ChatMessage;
  onSave: (content: MessageContent) => void | Promise<void>;
  onCancel: () => void;
}

// 从 ContentBlock[] 构建初始 pendingImages 和 HTML
function initFromContent(content: MessageContent): { html: string; images: PendingImage[] } {
  if (typeof content === "string") {
    return { html: escapeHtml(content).replace(/\n/g, "<br/>"), images: [] };
  }
  const blocks = content as ContentBlock[];
  const images: PendingImage[] = [];
  // 先创建 PendingImage 条目，再生成 HTML（保证 data-image-id 一致）
  for (const block of blocks) {
    if (block.type === "image_url") {
      const id = generateUUID();
      images.push({ id, file: new File([], ""), dataUrl: block.image_url.url });
    }
  }
  const html = contentBlocksToHtml(blocks, images);
  return { html, images };
}

export default function MessageEditor({ message, onSave, onCancel }: MessageEditorProps) {
  // 懒初始化 — MessageEditor 每次编辑时都是新挂载
  const [initial] = useState(() => initFromContent(message.content));
  const [input, setInput] = useState(initial.html);
  const [pendingImages, setPendingImages] = useState<PendingImage[]>(initial.images);
  const inputRef = useRef<HTMLDivElement>(null);

  const addPendingImage = useCallback(async (file: File) => {
    if (!file.type.startsWith("image/")) return null;
    if (file.size > DIMENSIONS.MAX_PASTE_IMAGE_SIZE) return null;
    const id = generateUUID();
    const dataUrl = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.readAsDataURL(file);
    });
    setPendingImages((prev) => [...prev, { id, file, dataUrl }]);
    return { id, dataUrl };
  }, []);

  const removePendingImage = useCallback((id: string) => {
    setPendingImages((prev) => prev.filter((img) => img.id !== id));
  }, []);

  const handleSave = async () => {
    const blocks = extractContentBlocks(inputRef.current, pendingImages);
    // 降级：只有 1 个 text block 时转为 string
    const content: MessageContent =
      blocks.length === 1 && blocks[0].type === "text"
        ? blocks[0].text
        : blocks.length === 0
          ? ""
          : blocks;
    // 无变化检测
    const initialBlocks = extractContentBlocks(
      (() => {
        const div = document.createElement("div");
        div.innerHTML = initial.html;
        return div;
      })(),
      initial.images,
    );
    const unchanged =
      JSON.stringify(content) === JSON.stringify(
        initialBlocks.length === 1 && initialBlocks[0].type === "text"
          ? initialBlocks[0].text
          : initialBlocks.length === 0 ? "" : initialBlocks,
      );
    if (unchanged) {
      onCancel();
      return;
    }
    await onSave(content);
  };

  return (
    <div className="message-edit-box">
      <RichInput
        ref={inputRef}
        value={input}
        onChange={(html) => setInput(html)}
        onSend={handleSave}
        onPasteImage={addPendingImage}
        onRemoveImage={removePendingImage}
        pendingImages={pendingImages}
        placeholder="编辑消息..."
      />
      <div className="message-edit-actions">
        <button type="button" onClick={handleSave}>保存</button>
        <button type="button" onClick={onCancel}>取消</button>
      </div>
    </div>
  );
}