import { useMemo, useState } from 'react';
import Section from '@/components/Section';
import Reveal from '@/components/Reveal';
import { Formula, M, Sub } from '@/components/Math';
import { surprise, fmt } from '@/lib/entropy';

const W = 560;
const H = 300;
const PAD = { l: 46, r: 16, t: 18, b: 38 };

/** h(p) = -log2(p) 曲线图 */
function SurpriseCurve({ p }: { p: number }) {
  const yMax = 8;
  const xToPx = (x: number) => PAD.l + (x / 1) * (W - PAD.l - PAD.r);
  const yToPx = (y: number) => H - PAD.b - (Math.min(y, yMax) / yMax) * (H - PAD.t - PAD.b);

  const path = useMemo(() => {
    let d = '';
    for (let i = 0; i <= 200; i++) {
      const x = 0.001 + (i / 200) * 0.999;
      const y = surprise(x);
      d += `${i === 0 ? 'M' : 'L'}${xToPx(x).toFixed(1)},${yToPx(y).toFixed(1)} `;
    }
    return d;
  }, []);

  const hVal = surprise(p);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
      {/* 网格 */}
      {[1, 2, 4, 6, 8].map((y) => (
        <g key={y}>
          <line x1={PAD.l} x2={W - PAD.r} y1={yToPx(y)} y2={yToPx(y)} stroke="rgba(255,255,255,0.07)" />
          <text x={PAD.l - 8} y={yToPx(y) + 4} textAnchor="end" fontSize="11" fill="rgba(255,255,255,0.4)" fontFamily="monospace">
            {y}
          </text>
        </g>
      ))}
      {[0.25, 0.5, 0.75, 1].map((x) => (
        <g key={x}>
          <line x1={xToPx(x)} x2={xToPx(x)} y1={PAD.t} y2={H - PAD.b} stroke="rgba(255,255,255,0.07)" />
          <text x={xToPx(x)} y={H - PAD.b + 18} textAnchor="middle" fontSize="11" fill="rgba(255,255,255,0.4)" fontFamily="monospace">
            {x}
          </text>
        </g>
      ))}
      <text x={W - PAD.r} y={H - 8} textAnchor="end" fontSize="12" fill="rgba(255,255,255,0.5)" fontFamily="serif" fontStyle="italic">
        p
      </text>
      <text x={14} y={PAD.t + 4} fontSize="12" fill="rgba(255,255,255,0.5)" fontFamily="serif" fontStyle="italic">
        h(p)
      </text>
      <path d={path} fill="none" stroke="url(#sg)" strokeWidth="2.5" />
      <defs>
        <linearGradient id="sg" x1="0" x2="1">
          <stop offset="0" stopColor="#ff8c00" />
          <stop offset="1" stopColor="#ffb800" />
        </linearGradient>
      </defs>
      {/* 当前点 */}
      <line x1={xToPx(p)} x2={xToPx(p)} y1={yToPx(hVal)} y2={H - PAD.b} stroke="rgba(255,184,0,0.4)" strokeDasharray="3 4" />
      <circle cx={xToPx(p)} cy={yToPx(hVal)} r="7" fill="#ffb800" opacity="0.25" />
      <circle cx={xToPx(p)} cy={yToPx(hVal)} r="4" fill="#ffb800" />
      <text
        x={Math.min(xToPx(p) + 12, W - 130)}
        y={yToPx(hVal) - 10}
        fontSize="13"
        fill="#ffd166"
        fontFamily="monospace"
      >
        h = {fmt(hVal, 2)} bit
      </text>
    </svg>
  );
}

const EXAMPLES = [
  { name: '太阳明天从东方升起', p: 0.999999 },
  { name: '抛硬币出正面', p: 0.5 },
  { name: '掷骰子掷出 6', p: 1 / 6 },
  { name: '买彩票中头奖', p: 1 / 17721088 },
];

export default function S1Surprise() {
  const [pPct, setPPct] = useState(50); // 0-100
  const p = Math.max(pPct / 100, 0.001);

  return (
    <Section
      id="s1"
      index="01"
      kicker="Surprise"
      title="信息量：惊讶的度量"
      lead="1948 年，克劳德·香农（Claude Shannon）在《通信的数学理论》中问了一个朴素的问题：一条消息到底携带了多少「信息」？他的答案是——信息就是惊讶。一件事越不可能发生，它真的发生时带给你的信息量就越大。"
    >
      <Reveal>
        <div className="grid gap-4 md:grid-cols-2">
          {EXAMPLES.map((e, i) => (
            <div
              key={e.name}
              className="flex items-center justify-between rounded-xl border border-white/10 bg-white/[0.03] px-5 py-4"
              style={{ transitionDelay: `${i * 60}ms` }}
            >
              <div>
                <p className="text-sm text-white/80">{e.name}</p>
                <p className="mt-1 font-mono text-xs text-white/40">
                  p ≈ {e.p >= 0.001 ? e.p.toFixed(4) : '1/17,721,088'}
                </p>
              </div>
              <div className="text-right">
                <p className="font-mono text-xl font-bold text-amber-300">{fmt(surprise(e.p), 2)}</p>
                <p className="text-xs text-white/40">bit</p>
              </div>
            </div>
          ))}
        </div>
      </Reveal>

      <Reveal delay={100}>
        <p className="leading-relaxed text-white/70">
          几乎必然的事发生了，你毫无波澜（≈ 0 bit）；两千万分之一的彩票中奖了，这条消息价值约 24 bit。
          香农把单个事件的信息量定义为：
        </p>
        <Formula caption="p 越小，h 越大；p = 1 时 h = 0。底数取 2 时，单位是比特（bit）">
          h(<M>p</M>) = −log<Sub>2</Sub> <M>p</M>
        </Formula>
      </Reveal>

      <Reveal delay={150}>
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm font-medium text-white/80">拖动滑块，感受概率与信息量的关系</p>
            <p className="font-mono text-sm text-amber-300">
              p = {fmt(p, 3)} → h = {fmt(surprise(p), 2)} bit
            </p>
          </div>
          <input
            type="range"
            min={1}
            max={100}
            value={pPct}
            onChange={(e) => setPPct(Number(e.target.value))}
            className="slider-amber w-full"
            aria-label="事件概率"
          />
          <div className="mt-4">
            <SurpriseCurve p={p} />
          </div>
        </div>
      </Reveal>

      <Reveal delay={100}>
        <div className="rounded-xl border-l-2 border-amber-400/60 bg-amber-400/[0.06] px-5 py-4 text-sm leading-relaxed text-white/70">
          为什么取对数？因为信息量应该是「可加」的：两个独立事件同时发生，总惊讶度应当等于各自惊讶度之和，
          而概率是相乘的——只有对数能把乘法变成加法：log(<M>p</M>·<M>q</M>) = log <M>p</M> + log <M>q</M>。
          这个性质在后面的推导中至关重要。
        </div>
      </Reveal>
    </Section>
  );
}
