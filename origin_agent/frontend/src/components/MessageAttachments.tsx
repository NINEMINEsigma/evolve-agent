import { ChatMessage } from "../types";
import PlaylistPlayer from "./PlaylistPlayer";

interface MessageAttachmentsProps {
  message: ChatMessage;
  onImageClick: (src: string) => void;
}

export default function MessageAttachments({ message, onImageClick }: MessageAttachmentsProps) {
  const m = message;
  return (
    <>
      {m.imageMarkdown && (() => {
        const md = m.imageMarkdown;
        const match = md.match(/!\[(.*?)\]\(([^)]+)\)/);
        const altText = match ? match[1] : "";
        const imgSrc = match ? match[2] : "";
        return imgSrc ? (
          <a href="#" onClick={(e) => { e.preventDefault(); onImageClick(imgSrc); }} className="tool-image-link">
            <img src={imgSrc} alt={altText} className="tool-image" />
          </a>
        ) : null;
      })()}
      {m.audioUrl && (
        <div className="tool-audio">
          <audio controls={true} autoPlay={m.audioAutoplay} src={m.audioUrl} className="tool-audio-player">
            您的浏览器不支持音频播放
          </audio>
        </div>
      )}
      {m.playlist && m.playlist.length > 0 && (
        <PlaylistPlayer playlist={m.playlist} autoplay={m.playlistAutoplay ?? true} />
      )}
      {m.downloadInfo && (
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
      )}
    </>
  );
}