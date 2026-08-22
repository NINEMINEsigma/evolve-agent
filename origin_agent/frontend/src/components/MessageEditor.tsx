import { useState, useCallback, useRef } from "react";
import { ChatMessage, ContentBlock, MessageContent, PendingImage, PendingAudio, PendingVideo } from "../types";
import { generateUUID, escapeHtml, contentBlocksToHtml, extractContentBlocks } from "../utils";
import RichInput from "./RichInput";
import { DIMENSIONS } from "../constants/dimensions";

interface MessageEditorProps {
  message: ChatMessage;
  onSave: (content: MessageContent) => void | Promise<void>;
  onCancel: () => void;
}

const _AUDIO_MIME_TO_FORMAT: Record<string, string> = {
  "audio/wav": "wav",
  "audio/mpeg": "mp3",
  "audio/mp3": "mp3",
};

// 从 ContentBlock[] 构建初始 pendingImages/pendingAudios 和 HTML
function initFromContent(content: MessageContent): { html: string; images: PendingImage[]; audios: PendingAudio[]; videos: PendingVideo[] } {
  if (typeof content === "string") {
    return { html: escapeHtml(content).replace(/\n/g, "<br/>"), images: [], audios: [], videos: [] };
  }
  const blocks = content as ContentBlock[];
  const images: PendingImage[] = [];
  const audios: PendingAudio[] = [];
  const videos: PendingVideo[] = [];
  for (const block of blocks) {
    if (block.type === "image_url") {
      const id = generateUUID();
      images.push({ id, file: new File([], ""), dataUrl: block.image_url.url });
    } else if (block.type === "input_audio") {
      const id = generateUUID();
      const dataUrl = block.input_audio.data.startsWith("data:")
        ? block.input_audio.data
        : `data:audio/${block.input_audio.format};base64,${block.input_audio.data}`;
      audios.push({ id, file: new File([], ""), dataUrl, format: block.input_audio.format });
    } else if (block.type === "video_url") {
      const id = generateUUID();
      videos.push({ id, file: new File([], ""), dataUrl: block.video_url.url });
    }
  }
  const html = contentBlocksToHtml(blocks, images, audios, videos);
  return { html, images, audios, videos };
}

export default function MessageEditor({ message, onSave, onCancel }: MessageEditorProps) {
  const [initial] = useState(() => initFromContent(message.content));
  const [input, setInput] = useState(initial.html);
  const [pendingImages, setPendingImages] = useState<PendingImage[]>(initial.images);
  const [pendingAudios, setPendingAudios] = useState<PendingAudio[]>(initial.audios);
  const [pendingVideos, setPendingVideos] = useState<PendingVideo[]>(initial.videos);
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

  const addPendingAudio = useCallback(async (file: File) => {
    if (!file.type.startsWith("audio/")) return null;
    const format = _AUDIO_MIME_TO_FORMAT[file.type];
    if (!format) return null;
    if (file.size > DIMENSIONS.MAX_PASTE_AUDIO_SIZE) return null;
    const id = generateUUID();
    const dataUrl = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.readAsDataURL(file);
    });
    setPendingAudios((prev) => [...prev, { id, file, dataUrl, format }]);
    return { id, dataUrl };
  }, []);

  const removePendingAudio = useCallback((id: string) => {
    setPendingAudios((prev) => prev.filter((au) => au.id !== id));
  }, []);

  const addPendingVideo = useCallback(async (file: File) => {
    if (!file.type.startsWith("video/")) return null;
    if (file.type !== "video/mp4") return null;
    if (file.size > DIMENSIONS.MAX_PASTE_VIDEO_SIZE) return null;
    const id = generateUUID();
    const dataUrl = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.readAsDataURL(file);
    });
    setPendingVideos((prev) => [...prev, { id, file, dataUrl }]);
    return { id, dataUrl };
  }, []);

  const removePendingVideo = useCallback((id: string) => {
    setPendingVideos((prev) => prev.filter((vd) => vd.id !== id));
  }, []);

  const handleSave = async () => {
    const blocks = extractContentBlocks(inputRef.current, pendingImages, pendingAudios, pendingVideos);
    const content: MessageContent =
      blocks.length === 1 && blocks[0].type === "text"
        ? blocks[0].text
        : blocks.length === 0
          ? ""
          : blocks;
    const initialBlocks = extractContentBlocks(
      (() => {
        const div = document.createElement("div");
        div.innerHTML = initial.html;
        return div;
      })(),
      initial.images,
      initial.audios,
      initial.videos,
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
        onPasteAudio={addPendingAudio}
        onRemoveAudio={removePendingAudio}
        pendingAudios={pendingAudios}
        onPasteVideo={addPendingVideo}
        onRemoveVideo={removePendingVideo}
        pendingVideos={pendingVideos}
        placeholder="编辑消息..."
      />
      <div className="message-edit-actions">
        <button type="button" onClick={handleSave}>保存</button>
        <button type="button" onClick={onCancel}>取消</button>
      </div>
    </div>
  );
}