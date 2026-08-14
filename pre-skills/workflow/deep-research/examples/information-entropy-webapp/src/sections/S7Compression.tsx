import { useMemo, useState } from 'react';
import Section from '@/components/Section';
import Reveal from '@/components/Reveal';
import { fmt } from '@/lib/entropy';

const SYMBOLS = ['A', 'B', 'C', 'D'];
const P = [0.5, 0.25, 0.125, 0.125];
const CODES = ['0', '10', '110', '111'];

function sample(): number {
  const r = Math.random();
  let acc = 0;
  for (let i = 0; i < P.length; i++) {
    acc += P[i];
    if (r < acc) return i;
  }
  return P.length - 1;
}

export default function S7Compression() {
  const [message, setMessage] = useState<number[]>(() => Array.from({ length: 12 }, sample));
  const [stats, setStats] = useState<{ n: number; bits: number } | null>(null);

  const encoded = useMemo(() => message.map((i) => CODES[i]).join(''), [message]);
  const avgLen = useMemo(() => message.reduce((a, i) => a + CODES[i].length, 0) / message.length, [message]);

  const runSim = () => {
    const n = 100000;
    let bits = 0;
    for (let i = 0; i < n; i++) bits += CODES[sample()].length;
    setStats({ n, bits });
  };

  return (
    <Section
      id="s7"
      index="07"
      kicker="Source Coding"
      title="熵的物理意义：压缩的极限"
      lead="香农第一定理（信源编码定理）把熵从抽象的度量变成了可触摸的物理量：用最优编码压缩一个信源，每个符号平均至少需要 H(X) 个比特——多一分浪费，少一分不可能。熵就是信息的「体积」。"
    >
      <Reveal>
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
          <p className="mb-2 text-sm font-medium text-white/80">
            一个四符号信源：P(A)=½, P(B)=¼, P(C)=P(D)=⅛
          </p>
          <p className="mb-5 font-mono text-xs text-white/40">
            理论熵 H = ½·1 + ¼·2 + ⅛·3 + ⅛·3 = 1.75 bit/符号 · 定长编码需要 2 bit/符号
          </p>

          <div className="grid items-center gap-8 md:grid-cols-2">
            {/* 哈夫曼树 */}
            <svg viewBox="0 0 340 230" className="mx-auto w-full max-w-sm">
              <defs>
                <marker id="dot" markerWidth="4" markerHeight="4" refX="2" refY="2">
                  <circle cx="2" cy="2" r="2" fill="#ffb800" />
                </marker>
              </defs>
              {/* 边 */}
              {[
                { x1: 170, y1: 30, x2: 60, y2: 90, label: '0' },
                { x1: 170, y1: 30, x2: 260, y2: 90, label: '1' },
                { x1: 260, y1: 90, x2: 190, y2: 150, label: '0' },
                { x1: 260, y1: 90, x2: 310, y2: 150, label: '1' },
                { x1: 310, y1: 150, x2: 260, y2: 205, label: '0' },
                { x1: 310, y1: 150, x2: 335, y2: 205, label: '1' },
              ].map((e, i) => (
                <g key={i}>
                  <line x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2} stroke="rgba(255,184,0,0.5)" strokeWidth="1.5" />
                  <text x={(e.x1 + e.x2) / 2 - 8} y={(e.y1 + e.y2) / 2} fontSize="12" fill="#ffd166" fontFamily="monospace">
                    {e.label}
                  </text>
                </g>
              ))}
              {/* 内部节点 */}
              {[
                { x: 170, y: 30 },
                { x: 260, y: 90 },
                { x: 310, y: 150 },
              ].map((n, i) => (
                <circle key={i} cx={n.x} cy={n.y} r="5" fill="#0a0a0a" stroke="#ffb800" strokeWidth="1.5" />
              ))}
              {/* 叶子 */}
              {[
                { x: 60, y: 90, s: 'A', code: '0', p: '½' },
                { x: 190, y: 150, s: 'B', code: '10', p: '¼' },
                { x: 260, y: 205, s: 'C', code: '110', p: '⅛' },
                { x: 335, y: 205, s: 'D', code: '111', p: '⅛' },
              ].map((l) => (
                <g key={l.s}>
                  <rect x={l.x - 22} y={l.y - 14} width="44" height="30" rx="8" fill="rgba(255,184,0,0.15)" stroke="#ffb800" />
                  <text x={l.x} y={l.y + 5} textAnchor="middle" fontSize="13" fill="#ffe9b3" fontWeight="bold">
                    {l.s}
                  </text>
                  <text x={l.x} y={l.y + 30} textAnchor="middle" fontSize="10" fill="rgba(255,255,255,0.45)" fontFamily="monospace">
                    {l.code}（p={l.p}）
                  </text>
                </g>
              ))}
            </svg>

            <div className="space-y-3">
              <p className="text-sm text-white/60">哈夫曼编码：越常见的符号，码字越短。</p>
              {SYMBOLS.map((s, i) => (
                <div key={s} className="flex items-center gap-3">
                  <span className="w-6 text-center font-bold text-white/85">{s}</span>
                  <div className="h-6 rounded-md bg-amber-400/25" style={{ width: `${P[i] * 320}px` }} />
                  <span className="font-mono text-xs text-white/50">
                    p={fmt(P[i], 3)} → 码长 {CODES[i].length}
                  </span>
                </div>
              ))}
              <p className="pt-2 font-mono text-sm text-white/70">
                平均码长 L = <b className="text-amber-300">1.75</b> = H(X)，恰好触到理论下限
              </p>
            </div>
          </div>
        </div>
      </Reveal>

      <Reveal delay={100}>
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm font-medium text-white/80">随机电报机：用这个信源发一条消息</p>
            <div className="flex gap-2">
              <button
                onClick={() => setMessage(Array.from({ length: 12 }, sample))}
                className="rounded-full border border-amber-400/40 bg-amber-400/10 px-4 py-1.5 text-sm text-amber-200 transition-all hover:scale-105 hover:bg-amber-400/20 active:scale-95"
              >
                换一条消息
              </button>
              <button
                onClick={runSim}
                className="rounded-full border border-white/15 px-4 py-1.5 text-sm text-white/60 transition-colors hover:border-amber-400/50 hover:text-amber-200"
              >
                连发 100,000 个符号
              </button>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-1 font-mono">
            {message.map((m, i) => (
              <span key={i} className="rounded bg-white/[0.06] px-2 py-1 text-sm text-white/85">
                {SYMBOLS[m]}
              </span>
            ))}
            <span className="mx-2 text-white/30">→</span>
            <span className="break-all text-xs leading-6 text-amber-200/80">{encoded}</span>
          </div>
          <p className="mt-3 font-mono text-sm text-white/60">
            本条消息平均 {fmt(avgLen, 2)} bit/符号
            {stats && (
              <span className="ml-4 text-white/45">
                十万次模拟：{stats.bits.toLocaleString()} bit / {stats.n.toLocaleString()} 符号 ={' '}
                <b className="text-amber-300">{fmt(stats.bits / stats.n, 4)}</b> bit/符号 → 收敛于 1.75
              </span>
            )}
          </p>
        </div>
      </Reveal>

      <Reveal delay={120}>
        <div className="rounded-xl border-l-2 border-amber-400/60 bg-amber-400/[0.06] px-5 py-4 text-sm leading-relaxed text-white/70">
          这条定理支配着数字世界的一切：ZIP、JPEG、MP3、5G 信道编码……所有压缩算法都在追逐熵这个下限。
          反过来也成立：<strong className="text-white/90">任何能更好压缩数据的系统，都更深刻地「理解」了数据的分布</strong>——
          这句话是通往下一章的钥匙。
        </div>
      </Reveal>
    </Section>
  );
}
