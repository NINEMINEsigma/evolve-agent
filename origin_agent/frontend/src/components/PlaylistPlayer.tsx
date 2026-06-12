import { useEffect, useRef, useState, useCallback } from "react";
import { PlaylistEntry } from "../types";
import { formatTimeSec } from "../utils";

export default function PlaylistPlayer({ playlist, autoplay }: { playlist: PlaylistEntry[]; autoplay: boolean }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [expanded, setExpanded] = useState(true);

  useEffect(() => {
    setCurrentIndex(0);
    setCurrentTime(0);
    setDuration(0);
    setIsPlaying(false);
  }, [playlist]);

  const playIndex = useCallback((idx: number) => {
    if (idx < 0 || idx >= playlist.length) return;
    setCurrentIndex(idx);
    setCurrentTime(0);
    setDuration(0);
  }, [playlist.length]);

  const handlePrev = useCallback(() => {
    playIndex(currentIndex - 1);
  }, [currentIndex, playIndex]);

  const handleNext = useCallback(() => {
    playIndex(currentIndex + 1);
  }, [currentIndex, playIndex]);

  const handleEnded = useCallback(() => {
    if (currentIndex + 1 < playlist.length) {
      playIndex(currentIndex + 1);
    } else {
      setIsPlaying(false);
    }
  }, [currentIndex, playlist.length, playIndex]);

  const currentTrack = playlist[currentIndex];

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !currentTrack) return;
    audio.src = currentTrack.audio_url;
    audio.load();
    if (autoplay || currentIndex > 0) {
      const p = audio.play();
      p?.catch(() => {});
    }
  }, [currentIndex, currentTrack, autoplay]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const onTime = () => setCurrentTime(audio.currentTime);
    const onDur = () => setDuration(audio.duration || 0);
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("loadedmetadata", onDur);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    return () => {
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("loadedmetadata", onDur);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
    };
  }, []);

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      audio.play().catch(() => {});
    } else {
      audio.pause();
    }
  };

  const progressPercent = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div className="playlist-player">
      <div className="playlist-header">
        <span className="playlist-title">{currentTrack?.title || "Untitled"}</span>
        <span className="playlist-counter">{currentIndex + 1} / {playlist.length}</span>
      </div>

      <div className="playlist-progress-bar" onClick={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
        if (audioRef.current && duration > 0) {
          audioRef.current.currentTime = pct * duration;
        }
      }}>
        <div className="playlist-progress-fill" style={{ width: `${progressPercent}%` }} />
      </div>

      <div className="playlist-time">
        <span>{formatTimeSec(currentTime)}</span>
        <span>{formatTimeSec(duration)}</span>
      </div>

      <div className="playlist-controls">
        <button
          className="playlist-btn"
          onClick={handlePrev}
          disabled={currentIndex <= 0}
          title="上一首"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
            <path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" />
          </svg>
        </button>
        <button className="playlist-btn playlist-play-btn" onClick={togglePlay} title={isPlaying ? "暂停" : "播放"}>
          {isPlaying ? (
            <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
              <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
              <path d="M8 5v14l11-7z" />
            </svg>
          )}
        </button>
        <button
          className="playlist-btn"
          onClick={handleNext}
          disabled={currentIndex >= playlist.length - 1}
          title="下一首"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
            <path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" />
          </svg>
        </button>
        <button
          className="playlist-btn playlist-expand-btn"
          onClick={() => setExpanded(v => !v)}
          title={expanded ? "收起列表" : "展开列表"}
        >
          <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" style={{ transform: expanded ? "rotate(180deg)" : "none", transition: "transform 0.2s" }}>
            <path d="M7 10l5 5 5-5z" />
          </svg>
        </button>
      </div>

      {expanded && (
        <div className="playlist-tracks">
          {playlist.map((track, idx) => (
            <div
              key={idx}
              className={`playlist-track ${idx === currentIndex ? "active" : ""}`}
              onClick={() => playIndex(idx)}
            >
              <span className="playlist-track-num">{idx + 1}</span>
              <span className="playlist-track-title">{track.title || "Untitled"}</span>
              {idx === currentIndex && isPlaying && (
                <span className="playlist-track-playing">
                  <span />
                  <span />
                  <span />
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      <audio
        ref={audioRef}
        onEnded={handleEnded}
        style={{ display: "none" }}
      />
    </div>
  );
}