import { useEffect, useRef, useState } from "react";
import type { ReactElement } from "react";
import { SESSION_MEDIA } from "../../constants/sessionMedia";
import { mediaContentUrl } from "./api";
import { formatMediaLabel, mediaInputLabels as labels } from "./labels";
import type { MediaPreviewProps, MediaType } from "./types";

function MediaTypeIcon({ mediaType }: { mediaType: MediaType }): ReactElement {
  return <svg viewBox="0 0 48 48" className="session-media-type-icon" aria-hidden="true"
    fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    {mediaType === "image" && <><rect x="7" y="8" width="34" height="32" rx="3" />
      <circle cx="17" cy="18" r="3" /><path d="m8 34 10-9 7 6 8-12 8 15" /></>}
    {mediaType === "video" && <><rect x="6" y="8" width="36" height="32" rx="3" />
      <path d="m20 16 12 8-12 8z" /></>}
    {mediaType === "audio" && <><path d="M12 27v-5a12 12 0 0 1 24 0v5" />
      <rect x="8" y="25" width="8" height="13" rx="3" /><rect x="32" y="25" width="8" height="13" rx="3" />
      <path d="M36 38a5 5 0 0 1-5 5h-7" /></>}
  </svg>;
}

export default function MediaPreview({ item, sessionId, variant }: MediaPreviewProps): ReactElement {
  const [videoVisible, setVideoVisible] = useState(variant === "detail");
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const container = useRef<HTMLSpanElement | null>(null);
  const player = useRef<HTMLAudioElement | HTMLVideoElement | null>(null);
  const thumbnail = variant === "thumbnail";
  const showAudioIcon = thumbnail && item.media_type === "audio";
  const showIcon = !item.preview_available || showAudioIcon;
  const source = mediaContentUrl(sessionId, item.media_id);
  const videoMounted = item.media_type === "video" && (!thumbnail || videoVisible);
  const name = item.source_path ?? labels.mediaTypes[item.media_type];

  useEffect(() => {
    if (!thumbnail || item.media_type !== "video" || !item.preview_available) return;
    const element = container.current;
    if (element === null) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setVideoVisible(true);
        observer.disconnect();
      }
    }, { rootMargin: SESSION_MEDIA.VIDEO_PREVIEW_ROOT_MARGIN, threshold: SESSION_MEDIA.VIDEO_PREVIEW_THRESHOLD });
    observer.observe(element);
    return () => observer.disconnect();
  }, [thumbnail, item.media_type, item.preview_available, item.media_id, sessionId]);

  useEffect(() => {
    const element = player.current;
    // StrictMode会重放effect；清理后再次设置资源，不能留下无src的播放器。
    if (element && element.getAttribute("src") !== source) element.setAttribute("src", source);
    return () => {
      if (element) {
        element.pause();
        element.removeAttribute("src");
        element.load();
      }
    };
  }, [source, variant, videoMounted, item.preview_available]);

  return <span ref={container} className={`session-media-preview-view is-${variant} is-${item.media_type}`}>
    {showIcon && <span className="session-media-preview-placeholder">
      <MediaTypeIcon mediaType={item.media_type} />
      <span>{showAudioIcon ? labels.audioPreview : labels.previewUnavailable}</span>
    </span>}
    {!showIcon && <>
      {item.media_type === "image" && <img src={source} loading={thumbnail ? "lazy" : "eager"}
        alt={formatMediaLabel(labels.imageAlt, { name })} className={loaded ? "is-loaded" : ""}
        onLoad={() => setLoaded(true)} onError={() => setFailed(true)} />}
      {videoMounted && <video src={source} controls={!thumbnail} muted={thumbnail} preload="metadata"
        tabIndex={thumbnail ? undefined : 0} ref={(element) => { player.current = element; }}
        className={loaded ? "is-loaded" : ""} aria-label={labels.videoPreview}
        onLoadedMetadata={(event) => { if (thumbnail) event.currentTarget.currentTime = 0; }}
        onLoadedData={() => setLoaded(true)} onError={() => setFailed(true)} />}
      {item.media_type === "audio" && !thumbnail && <audio src={source} controls preload="metadata"
        ref={(element) => { player.current = element; }}
        aria-label={labels.mediaTypes.audio} onError={() => setFailed(true)} />}
      {item.media_type !== "audio" && !loaded && <span className="session-media-preview-placeholder">
        <MediaTypeIcon mediaType={item.media_type} />
        <span>{failed ? labels.previewFailed : labels.previewLoading}</span>
      </span>}
      {failed && item.media_type === "audio" && <span className="session-media-warning" role="alert">{labels.previewFailed}</span>}
    </>}
  </span>;
}
