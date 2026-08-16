// 录音后处理管线：MediaRecorder 原生容器 Blob → 解码 PCM → 起始静音裁剪 → 单声道化 → MP3 编码。
// 录音阶段不引入 AudioContext（其挂起态与采集时序是开头空白的根因），解码在录音结束后离线进行；
// 起始静音在 PCM 域确定性裁剪，不依赖任何采集 API 的时序表现。

import { Mp3Encoder } from "@breezystack/lamejs";

export interface Mp3ConversionResult {
  file: File;
  durationSec: number;
}

const MP3_BIT_RATE_KBPS = 128;
const ENCODE_CHUNK = 1152; // lamejs 内部帧粒度
const SILENCE_THRESHOLD = 0.006; // 峰值阈值，≈ -44 dBFS；高于收敛期底噪、远低于语音
const ONSET_WINDOW_SEC = 0.01; // 10ms 滑窗取峰值，避免单个爆点样本误判为语音起点
const PREROLL_SEC = 0.08; // 起点前保留 80ms，避免吃掉语音起始的弱音

export async function convertRecordingToMp3(
  blob: Blob,
  filename = "recording.mp3",
): Promise<Mp3ConversionResult | null> {
  const audio = await decodeBlob(blob);
  if (!audio) return null;

  const mono = mixdownToMono(audio);
  const start = findOnset(mono, audio.sampleRate);
  const trimmed = start > 0 ? mono.subarray(start) : mono;
  if (trimmed.length === 0) return null;

  const mp3 = encodeMp3(trimmed, audio.sampleRate);
  const file = new File([mp3], filename, { type: "audio/mpeg" });
  return { file, durationSec: trimmed.length / audio.sampleRate };
}

async function decodeBlob(blob: Blob): Promise<AudioBuffer | null> {
  try {
    const ctx = new AudioContext();
    try {
      const buf = await blob.arrayBuffer();
      // decodeAudioData 不要求 context 处于 running 态，挂起态下同样可用
      return await ctx.decodeAudioData(buf);
    } finally {
      await ctx.close();
    }
  } catch {
    return null;
  }
}

function mixdownToMono(buffer: AudioBuffer): Float32Array {
  if (buffer.numberOfChannels === 1) return buffer.getChannelData(0);
  const len = buffer.length;
  const out = new Float32Array(len);
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    const data = buffer.getChannelData(c);
    for (let i = 0; i < len; i++) out[i] += data[i];
  }
  const inv = 1 / buffer.numberOfChannels;
  for (let i = 0; i < len; i++) out[i] *= inv;
  return out;
}

// 找到首个峰值超过阈值的窗口，返回扣除预 rolling 后的起始采样下标；全静音返回 0（不裁剪）
function findOnset(pcm: Float32Array, sampleRate: number): number {
  const win = Math.max(1, Math.floor(sampleRate * ONSET_WINDOW_SEC));
  const preRoll = Math.floor(sampleRate * PREROLL_SEC);
  for (let i = 0; i + win <= pcm.length; i += win) {
    let peak = 0;
    for (let j = i; j < i + win; j++) {
      const a = Math.abs(pcm[j]);
      if (a > peak) peak = a;
    }
    if (peak >= SILENCE_THRESHOLD) return Math.max(0, i - preRoll);
  }
  return 0;
}

function encodeMp3(pcm: Float32Array, sampleRate: number): Uint8Array {
  const encoder = new Mp3Encoder(1, sampleRate, MP3_BIT_RATE_KBPS);
  const parts: Uint8Array[] = [];
  const int16 = new Int16Array(ENCODE_CHUNK);
  for (let i = 0; i < pcm.length; i += ENCODE_CHUNK) {
    const n = Math.min(ENCODE_CHUNK, pcm.length - i);
    for (let j = 0; j < n; j++) {
      const s = Math.max(-1, Math.min(1, pcm[i + j]));
      int16[j] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    const buf = encoder.encodeBuffer(int16.subarray(0, n));
    if (buf.length > 0) parts.push(buf);
  }
  const tail = encoder.flush();
  if (tail.length > 0) parts.push(tail);

  let total = 0;
  for (const p of parts) total += p.length;
  const out = new Uint8Array(total);
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}