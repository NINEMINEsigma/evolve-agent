import { ChatMessage } from "../types";
import type { MessageResourceResolver } from "./primitives/MessageRenderEnvironment";
import { useMessageRenderEnvironment } from "./primitives/MessageRenderEnvironment";

interface MessageAttachmentsProps {
  message: ChatMessage;
  onImageClick: (src: string) => void;
  /**
   * 资源解析器：live 缺省时原样使用引用；offline 由环境注入。
   * 下载附件（downloadInfo）不属于离线保存范围，解析器只作用于图片媒体。
   */
  resolveResource?: MessageResourceResolver;
}

export default function MessageAttachments({ message, onImageClick, resolveResource }: MessageAttachmentsProps) {
  const environment = useMessageRenderEnvironment();
  const offline = environment.mode === "offline";
  const m = message;
  return (
    <>
      {m.imageMarkdown && (() => {
        const md = m.imageMarkdown;
        const match = md.match(/!\[(.*?)\]\(([^)]+)\)/);
        const altText = match ? match[1] : "";
        const rawSrc = match ? match[2] : "";
        const imgSrc = rawSrc ? (resolveResource ? resolveResource(rawSrc, "image") : rawSrc) : "";
        if (rawSrc && !imgSrc) {
          return (
            <span className="offline-resource-placeholder" data-offline-resource="image">
              {environment.labels?.resourceUnavailable ?? "resource unavailable offline"}
            </span>
          );
        }
        return imgSrc ? (
          <a href="#" onClick={(e) => { e.preventDefault(); onImageClick(imgSrc); }} className="tool-image-link">
            <img src={imgSrc} alt={altText} className="tool-image" />
          </a>
        ) : null;
      })()}
      {m.downloadInfo && (offline ? (
        // 离线：普通下载附件不纳入保存，只保留文件名与文字 URL 说明，不提供失效下载按钮。
        <div className="tool-download offline-download-note">
          <span className="offline-download-label">{environment.labels?.attachment ?? "Attachment not saved offline"}</span>
          <span className="offline-download-filename">{m.downloadInfo.filename}</span>
          <span className="offline-download-url">{m.downloadInfo.url}</span>
        </div>
      ) : (
        <div className="tool-download">
          <a href={m.downloadInfo.url} className="download-btn" download={m.downloadInfo.filename}>
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            下载 {m.downloadInfo.filename}
          </a>
          {m.downloadInfo.size != null && (
            <span className="download-size">（{(m.downloadInfo.size / 1024).toFixed(1)} KB）</span>
          )}
        </div>
      ))}
    </>
  );
}