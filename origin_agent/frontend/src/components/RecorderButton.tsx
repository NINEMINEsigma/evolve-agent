import { useCallback } from "react";
import { useAudioRecorder } from "../hooks/useAudioRecorder";
import { formatTimeSec } from "../utils";

interface RecorderButtonProps {
  onRecordingComplete: (file: File) => void;
  disabled?: boolean;
}

export default function RecorderButton({ onRecordingComplete, disabled }: RecorderButtonProps) {
  const { isRecording, duration, startRecording, stopRecording, error } = useAudioRecorder();

  // 点击切换录音状态
  const handleClick = useCallback(async () => {
    if (disabled) return;

    if (isRecording) {
      const file = await stopRecording();
      if (file) {
        onRecordingComplete(file);
      }
    } else {
      try {
        await startRecording();
      } catch (err) {
        console.error("[RecorderButton] startRecording failed", err);
      }
    }
  }, [disabled, isRecording, startRecording, stopRecording, onRecordingComplete]);

  return (
    <div className="recorder-wrapper">
      <button
        className={`recorder-btn ${isRecording ? "recording" : ""}`}
        onClick={handleClick}
        disabled={disabled}
        data-tooltip={isRecording ? `录音中 ${formatTimeSec(duration)}` : "点击开始录音"}
        type="button"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
          {isRecording ? (
            <rect x="6" y="6" width="12" height="12" rx="2" />
          ) : (
            <>
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" y1="19" x2="12" y2="23" />
              <line x1="8" y1="23" x2="16" y2="23" />
            </>
          )}
        </svg>
      </button>
      {error && <div className="recorder-error">{error}</div>}
    </div>
  );
}