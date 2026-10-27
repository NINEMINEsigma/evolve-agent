import { useCallback, useEffect, useRef, useState } from "react";
import type { UseAudioRecorderReturn } from "@preview-original/audio-recorder";
export type { UseAudioRecorderReturn } from "@preview-original/audio-recorder";

const SAMPLE_RATE = 16000;
const DURATION_SECONDS = 3;

/** 生成单声道 PCM WAV，不创建 AudioContext，也不访问设备。 */
export function createPreviewWavBlob(): Blob {
  const samples = SAMPLE_RATE * DURATION_SECONDS;
  const buffer = new ArrayBuffer(44 + samples * 2);
  const view = new DataView(buffer);
  const text = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index += 1) view.setUint8(offset + index, value.charCodeAt(index));
  };
  text(0, "RIFF"); view.setUint32(4, buffer.byteLength - 8, true);
  text(8, "WAVE"); text(12, "fmt "); view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, SAMPLE_RATE, true); view.setUint32(28, SAMPLE_RATE * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, "data"); view.setUint32(40, samples * 2, true);
  for (let index = 0; index < samples; index += 1) {
    const time = index / SAMPLE_RATE;
    const envelope = Math.min(time * 20, (DURATION_SECONDS - time) * 20, 1);
    const pulse = 0.5 + 0.5 * Math.cos(time * Math.PI * 4);
    view.setInt16(44 + index * 2, Math.round(Math.sin(time * Math.PI * 2 * 440) * envelope * pulse * 2200), true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

export function useAudioRecorder(): UseAudioRecorderReturn {
  const [isRecording, setRecording] = useState(false);
  const [duration, setDuration] = useState(0);
  const active = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; active.current = false; };
  }, []);
  const startRecording = useCallback(async (): Promise<void> => {
    if (!mounted.current) return;
    active.current = true;
    setRecording(true);
    setDuration(DURATION_SECONDS);
  }, []);
  const stopRecording = useCallback(async (): Promise<File | null> => {
    if (!mounted.current || !active.current) return null;
    active.current = false;
    setRecording(false);
    return new File([createPreviewWavBlob()], "preview-recording.wav", { type: "audio/wav", lastModified: 0 });
  }, []);
  return { isRecording, duration, startRecording, stopRecording, error: null };
}
