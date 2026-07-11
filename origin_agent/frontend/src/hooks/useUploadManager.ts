import { useCallback, useRef, useState } from "react";
import { ChatMessage, ContentBlock, DownloadInfo, MessageContent, PlaylistEntry, SessionInfo } from "../types";
import { generateUUID } from "../utils";

const MAX_PASTE_IMAGE_SIZE = 20 * 1024 * 1024;

export interface PendingImage {
  id: string;
  file: File;
  dataUrl: string;
}

export type AddMessageFn = (
  role: ChatMessage["role"],
  content: MessageContent,
  imageMarkdown?: string,
  downloadInfo?: DownloadInfo,
  audioUrl?: string,
  audioAutoplay?: boolean,
  playlist?: PlaylistEntry[],
  playlistAutoplay?: boolean,
  messageIndex?: number
) => void;

export interface UploadManagerDeps {
  wsRef: React.RefObject<WebSocket | null>;
  sessions: SessionInfo[];
  sessionId: string;
  addMessage: AddMessageFn;
}

export interface UploadManager {
  uploading: boolean;
  setUploading: React.Dispatch<React.SetStateAction<boolean>>;
  pendingImages: PendingImage[];
  setPendingImages: React.Dispatch<React.SetStateAction<PendingImage[]>>;
  inputRef: React.RefObject<HTMLDivElement>;
  fileInputRef: React.RefObject<HTMLInputElement>;
  handleFileUpload: (files: FileList | File[] | null) => void;
  handleFileInputChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  handleUploadClick: () => Promise<void>;
  addPendingImage: (file: File) => Promise<{ id: string; dataUrl: string } | null>;
  removePendingImage: (id: string) => void;
  handlePasteImages: (file: File) => Promise<{ id: string; dataUrl: string } | null>;
  extractContentBlocks: (el: HTMLDivElement | null, images: PendingImage[]) => ContentBlock[];
}

export function useUploadManager({
  wsRef,
  sessions,
  sessionId,
  addMessage,
}: UploadManagerDeps): UploadManager {
  const [uploading, setUploading] = useState(false);
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([]);
  const inputRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const isLocal = typeof window !== "undefined" &&
    (window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost");

  const handleFileUpload = useCallback((files: FileList | File[] | null) => {
    const isArchived = sessions.find((s) => s.id === sessionId)?.status === "archived";
    if (!files || files.length === 0 || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || isArchived) return;

    setUploading(true);
    let completed = 0;
    const total = files.length;

    Array.from(files).forEach((file) => {
      const localPath = (file as unknown as Record<string, string>).path || (file as unknown as Record<string, string>).webkitRelativePath || "";

      if (localPath) {
        wsRef.current!.send(
          JSON.stringify({
            type: "file_upload",
            filename: file.name,
            mime_type: file.type || "application/octet-stream",
            local_path: localPath,
            file_data: "",
          })
        );
        addMessage("system", `📎 上传中（硬链接）：${file.name}`);
        completed++;
        if (completed === total) {
          setUploading(false);
          if (fileInputRef.current) fileInputRef.current.value = "";
        }
        return;
      }

      const reader = new FileReader();
      reader.onload = () => {
        const base64 = (reader.result as string).split(",")[1] || "";
        wsRef.current!.send(
          JSON.stringify({
            type: "file_upload",
            filename: file.name,
            mime_type: file.type || "application/octet-stream",
            file_data: base64,
          })
        );
        addMessage("system", `📎 正在上传：${file.name} (${(file.size / 1024).toFixed(1)}KB)...`);
        completed++;
        if (completed === total) {
          setUploading(false);
          if (fileInputRef.current) fileInputRef.current.value = "";
        }
      };
      reader.onerror = () => {
        addMessage("error", `文件读取失败：${file.name}`);
        completed++;
        if (completed === total) setUploading(false);
      };
      reader.readAsDataURL(file);
    });
  }, [sessions, sessionId, addMessage, wsRef]);

  const addPendingImage = useCallback((file: File) => {
    return new Promise<{ id: string; dataUrl: string } | null>((resolve) => {
      if (!file.type.startsWith("image/")) {
        addMessage("error", "仅支持粘贴图片文件");
        resolve(null);
        return;
      }
      if (file.size > MAX_PASTE_IMAGE_SIZE) {
        addMessage("error", `图片超过 20MB 限制：${file.name}`);
        resolve(null);
        return;
      }
      const id = generateUUID();
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = reader.result as string;
        setPendingImages((prev) => [...prev, { id, file, dataUrl }]);
        resolve({ id, dataUrl });
      };
      reader.onerror = () => {
        addMessage("error", `读取图片失败：${file.name}`);
        resolve(null);
      };
      reader.readAsDataURL(file);
    });
  }, [addMessage]);

  const removePendingImage = useCallback((id: string) => {
    setPendingImages((prev) => prev.filter((img) => img.id !== id));
  }, []);

  const handlePasteImages = useCallback((file: File) => {
    return addPendingImage(file);
  }, [addPendingImage]);

  const handleUploadClick = useCallback(async () => {
    if (isLocal) {
      try {
        const resp = await fetch("/api/file-picker", { method: "POST" });
        const data = await resp.json();
        if (data.uploaded && data.files) {
          for (const f of data.files) {
            addMessage("system", `📎 ${f.method === "hardlink" ? "硬链接" : "复制"}: ${f.filename} (${(f.size / 1024).toFixed(1)}KB)`);
          }
        } else if (data.error) {
          addMessage("error", `文件选择失败: ${data.error}`);
          if (isLocal) fileInputRef.current?.click();
        }
      } catch (err) {
        addMessage("error", `文件选择异常: ${err}`);
        fileInputRef.current?.click();
      }
    } else {
      fileInputRef.current?.click();
    }
  }, [addMessage, isLocal]);

  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    handleFileUpload(e.target.files);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, [handleFileUpload]);

  const extractContentBlocks = useCallback((el: HTMLDivElement | null, images: PendingImage[]): ContentBlock[] => {
    if (!el) return [];
    const blocks: ContentBlock[] = [];
    const imageMap = new Map(images.map((img) => [img.id, img]));

    const imageNodes = el.querySelectorAll<HTMLSpanElement>(".input-inline-image");
    if (imageNodes.length === 0) {
      const text = (el.innerText || "").replace(/\u200B/g, "").replace(/\n{3,}/g, "\n\n").trim();
      if (text) blocks.push({ type: "text", text });
      return blocks;
    }

    const imagePositions = new Map<Node, PendingImage>();
    imageNodes.forEach((node) => {
      const id = node.dataset.imageId;
      const img = id ? imageMap.get(id) : undefined;
      if (img) imagePositions.set(node, img);
    });

    let currentText = "";
    const flushText = () => {
      const cleaned = currentText.replace(/\u200B/g, "").replace(/\n{3,}/g, "\n\n").trim();
      if (cleaned) blocks.push({ type: "text", text: cleaned });
      currentText = "";
    };

    const walk = (node: Node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        currentText += node.textContent || "";
        return;
      }
      if (node.nodeType === Node.ELEMENT_NODE) {
        const el = node as HTMLElement;
        if (imagePositions.has(el)) {
          flushText();
          blocks.push({ type: "image_url", image_url: { url: imagePositions.get(el)!.dataUrl } });
          return;
        }
        for (const child of Array.from(el.childNodes)) {
          if (child.nodeType === Node.ELEMENT_NODE && (child as HTMLElement).tagName === "BR") {
            currentText += "\n";
          } else {
            walk(child);
          }
        }
        if (el.tagName === "DIV") {
          currentText += "\n";
        }
      }
    };

    for (const child of Array.from(el.childNodes)) {
      walk(child);
    }
    flushText();
    return blocks;
  }, []);

  return {
    uploading,
    setUploading,
    pendingImages,
    setPendingImages,
    inputRef,
    fileInputRef,
    handleFileUpload,
    handleFileInputChange,
    handleUploadClick,
    addPendingImage,
    removePendingImage,
    handlePasteImages,
    extractContentBlocks,
  };
}
