// 录音 Hook：纯 MediaRecorder 采集 + 停止后离线转 MP3。
// 录音期间不创建 AudioContext（挂起态/采集时序是开头空白的根因）。
//
// 麦克风流跨录音保活复用（录完不 stop 轨）：重复 getUserMedia 时设备重开存在
// 供数空窗（轨处于 muted 态），期间语音会被静默吞掉；保活让捕获管线
// （AEC/AGC/NS）持续运行并保持收敛态，从结构上消除该空窗。代价：首次录音后
// 标签页常驻麦克风占用指示，流在组件卸载时释放。
//
// 每次录音持有独立的 CaptureSession（recorder/chunks 会话私有），
// 通过 sessionSeq 序号使过期的异步后续操作直接作废，避免快速连点时数据串扰。

import { useCallback, useEffect, useRef, useState } from "react";
import { convertRecordingToMp3 } from "../utils/audioEncoder";

export interface UseAudioRecorderReturn {
  isRecording: boolean;
  duration: number;
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<File | null>;
  error: string | null;
}

const MIN_DURATION_SEC = 0.5;
const UNMUTE_TIMEOUT_MS = 2000;

const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg;codecs=opus",
];

const ERROR_MESSAGES: Record<string, string> = {
  NotAllowedError: "请在浏览器设置中允许麦克风权限",
  NotFoundError: "未检测到麦克风设备",
  NotReadableError: "麦克风正被其他应用使用",
};

interface CaptureSession {
  id: number;
  recorder: MediaRecorder;
  chunks: Blob[];
}

function pickMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "";
  return MIME_CANDIDATES.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
}

// 捕获轨在设备首次打开/热插拔重开后可能短暂处于 muted（不供数）态，
// 等 unmute 再启动 MediaRecorder，否则开头语音会被静默吞掉；超时兜底防卡死
function waitForTrackData(track: MediaStreamTrack): Promise<void> {
  if (!track.muted) return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      window.clearTimeout(timer);
      track.removeEventListener("unmute", done);
      resolve();
    };
    const timer = window.setTimeout(done, UNMUTE_TIMEOUT_MS);
    track.addEventListener("unmute", done);
  });
}

export function useAudioRecorder(): UseAudioRecorderReturn {
  const [isRecording, setIsRecording] = useState(false);
  const [duration, setDuration] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const captureRef = useRef<CaptureSession | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const sessionSeqRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const startAtRef = useRef(0);

  const stopTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const startTimer = useCallback(() => {
    startAtRef.current = performance.now();
    setDuration(0);
    timerRef.current = window.setInterval(() => {
      setDuration((performance.now() - startAtRef.current) / 1000);
    }, 200);
  }, []);

  const releaseStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  // 丢弃进行中的采集（不等待编码结果），使关联的 stopRecording 后续逻辑失效；
  // 只停 recorder，不动保活的麦克风流
  const discardCapture = useCallback(() => {
    const cap = captureRef.current;
    captureRef.current = null;
    if (!cap) return;
    try {
      if (cap.recorder.state !== "inactive") cap.recorder.stop();
    } catch {
      // 已停止：忽略
    }
  }, []);

  useEffect(() => {
    return () => {
      sessionSeqRef.current++;
      stopTimer();
      discardCapture();
      releaseStream();
    };
  }, [stopTimer, discardCapture, releaseStream]);

  // 获取可用麦克风流：优先复用保活流；轨已 ended（设备拔出/系统回收）时重新申请
  const acquireStream = useCallback(async (): Promise<MediaStream> => {
    const existing = streamRef.current;
    if (existing) {
      const track = existing.getAudioTracks()[0];
      if (track && track.readyState === "live") return existing;
      releaseStream();
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    streamRef.current = stream;
    return stream;
  }, [releaseStream]);

  const startRecording = useCallback(async () => {
    setError(null);
    sessionSeqRef.current++;
    const sid = sessionSeqRef.current;
    discardCapture();
    setIsRecording(false);
    stopTimer();

    let stream: MediaStream;
    try {
      stream = await acquireStream();
    } catch (err) {
      const e = err as Error;
      setError(ERROR_MESSAGES[e.name] || `录音失败：${e.message}`);
      return;
    }

    // 会话已过期（等待期间用户连点/组件卸载）：流留给新会话复用，不释放
    if (sessionSeqRef.current !== sid) return;

    // 等捕获轨真正开始供数（首次申请或设备重开后可能短暂 muted）
    const track = stream.getAudioTracks()[0];
    if (track) await waitForTrackData(track);
    if (sessionSeqRef.current !== sid) return;

    const mimeType = pickMimeType();
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };

    captureRef.current = { id: sid, recorder, chunks };
    recorder.start();
    setIsRecording(true);
    startTimer();
  }, [acquireStream, discardCapture, stopTimer, startTimer]);

  const stopRecording = useCallback(async (): Promise<File | null> => {
    const cap = captureRef.current;
    if (!cap) return null;
    captureRef.current = null;
    const sid = cap.id;

    setIsRecording(false);
    stopTimer();

    // 先取到最终数据再停 recorder；onstop 保证最后一个 dataavailable 已落袋。
    // 流不停止：保活供下次录音复用，避免设备重开的供数空窗
    const blob = await new Promise<Blob>((resolve) => {
      cap.recorder.onstop = () =>
        resolve(new Blob(cap.chunks, { type: cap.recorder.mimeType || undefined }));
      try {
        cap.recorder.stop();
      } catch {
        resolve(new Blob(cap.chunks, { type: cap.recorder.mimeType || undefined }));
      }
    });

    if (blob.size === 0) return null;

    const result = await convertRecordingToMp3(blob);
    // 解码/编码期间用户已开始新会话：丢弃本次结果
    if (sessionSeqRef.current !== sid) return null;
    if (!result) {
      setError("音频解码失败，请重试");
      return null;
    }
    if (result.durationSec < MIN_DURATION_SEC) {
      setError("录音太短，已丢弃");
      return null;
    }
    return result.file;
  }, [stopTimer]);

  return { isRecording, duration, startRecording, stopRecording, error };
}