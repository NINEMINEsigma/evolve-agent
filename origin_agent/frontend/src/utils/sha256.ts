/**
 * SHA-256 工具：优先使用浏览器原生 Web Crypto，在远程普通 HTTP 环境
 * （crypto.subtle 不可用）或原生摘要调用失败时，回退到纯 TypeScript 实现。
 *
 * 备用实现严格遵循 FIPS 180-4，与 Python hashlib.sha256 在相同 UTF-8
 * 字节输入下产出完全一致的 64 位小写十六进制字符串。
 */

/** SHA-256 初始哈希值（前 8 个素数平方根的小数部分前 32 位）。 */
const H0 = new Uint32Array([
  0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
  0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
]);

/** SHA-256 轮常量（前 64 个素数立方根的小数部分前 32 位）。 */
const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
  0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
  0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
  0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
  0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
  0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

/** 32 位无符号右旋转。 */
function rotr(x: number, n: number): number {
  return ((x >>> n) | (x << (32 - n))) >>> 0;
}

/**
 * 纯 TypeScript SHA-256 实现。
 *
 * 按字节处理输入，执行 512-bit 分块、0x80 填充及 64-bit 大端位长度编码，
 * 输出 64 位小写十六进制字符串。与 Python hashlib.sha256 结果一致。
 */
export function sha256HexFallback(bytes: Uint8Array): string {
  // 预处理：追加 0x80，用 0 填充至 length ≡ 448 (mod 512)，再追加 64-bit 大端位长度。
  const bitLen = bytes.length * 8;
  const withPadding = new Uint8Array(bytes.length + 72);
  withPadding.set(bytes);
  withPadding[bytes.length] = 0x80;

  // 填充至 56 字节对齐（mod 64）
  const paddedLen = (Math.floor((bytes.length + 8) / 64) + 1) * 64;
  const full = new Uint8Array(paddedLen);
  full.set(bytes);
  full[bytes.length] = 0x80;

  // 64-bit 大端位长度（仅支持到 2^53 安全范围）
  const lenBytes = new DataView(full.buffer);
  const bitLenHigh = Math.floor(bitLen / 0x100000000);
  const bitLenLow = bitLen >>> 0;
  lenBytes.setUint32(paddedLen - 8, bitLenHigh, false);
  lenBytes.setUint32(paddedLen - 4, bitLenLow, false);

  // 初始化哈希值
  const h = new Uint32Array(H0);
  const w = new Uint32Array(64);
  const view = new DataView(full.buffer);

  // 逐 512-bit 分块处理
  for (let offset = 0; offset < paddedLen; offset += 64) {
    // W0-W15 从当前分块大端读取
    for (let i = 0; i < 16; i++) {
      w[i] = view.getUint32(offset + i * 4, false);
    }
    // W16-W63 计算
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }

    // 初始化工作变量
    let a = h[0], b = h[1], c = h[2], d = h[3];
    let e = h[4], f = h[5], g = h[6], hh = h[7];

    // 64 轮压缩
    for (let i = 0; i < 64; i++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const temp1 = (hh + S1 + ch + K[i] + w[i]) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (S0 + maj) >>> 0;

      hh = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }

    // 更新哈希值
    h[0] = (h[0] + a) >>> 0;
    h[1] = (h[1] + b) >>> 0;
    h[2] = (h[2] + c) >>> 0;
    h[3] = (h[3] + d) >>> 0;
    h[4] = (h[4] + e) >>> 0;
    h[5] = (h[5] + f) >>> 0;
    h[6] = (h[6] + g) >>> 0;
    h[7] = (h[7] + hh) >>> 0;
  }

  // 输出 64 位小写十六进制字符串
  const hexChars = "0123456789abcdef";
  let result = "";
  for (let i = 0; i < 8; i++) {
    result += hexChars[(h[i] >>> 28) & 0xf];
    result += hexChars[(h[i] >>> 24) & 0xf];
    result += hexChars[(h[i] >>> 20) & 0xf];
    result += hexChars[(h[i] >>> 16) & 0xf];
    result += hexChars[(h[i] >>> 12) & 0xf];
    result += hexChars[(h[i] >>> 8) & 0xf];
    result += hexChars[(h[i] >>> 4) & 0xf];
    result += hexChars[h[i] & 0xf];
  }
  return result;
}

/**
 * 统一 SHA-256 摘要接口。
 *
 * 安全上下文（HTTPS 或 localhost）优先使用浏览器原生 Web Crypto；
 * 远程普通 HTTP 环境下 crypto.subtle 不可用时自动回退到纯 TypeScript 实现。
 * 原生 digest() 的同步抛错和 Promise 拒绝均转入回退实现。
 */
export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (subtle) {
    try {
      const digest = await subtle.digest("SHA-256", bytes);
      return Array.from(new Uint8Array(digest), (v) =>
        v.toString(16).padStart(2, "0"),
      ).join("");
    } catch {
      // crypto.subtle 存在但调用失败（如非安全上下文限制），
      // 回退到纯 TypeScript 实现。
    }
  }
  return sha256HexFallback(bytes);
}
