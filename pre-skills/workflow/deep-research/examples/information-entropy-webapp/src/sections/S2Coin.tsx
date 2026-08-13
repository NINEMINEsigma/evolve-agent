import { useMemo, useState } from 'react';
import Section from '@/components/Section';
import Reveal from '@/components/Reveal';
import { Formula, M, Sub } from '@/components/Math';
import { binaryEntropy, entropy, fmt } from '@/lib/entropy';

const W = 560;
const H = 300;
const PAD = { l: 46, r: 16, t: 18, b: 38 };

function BinaryCurve({ p }: { p: number }) {
  const xToPx = (x: number) => PAD.l + x * (W - PAD.l - PAD.r);
  const yToPx = (y: number) => H - PAD.b - y * (H - PAD.t - PAD.b);

  const path = useMemo(() => {
    let d = '';
    for (let i = 0; i <= 200; i++) {
      const x = i / 200;
      d += `${i === 0 ? 'M' : 'L'}${xToPx(x).toFixed(1)},${yToPx(binaryEntropy(x)).toFixed(1)} `;
    }
    return d;
  }, []);

  const hp = binaryEntropy(p);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
      {[0.25, 0.5, 0.75, 1].map((y) => (
        <g key={y}>
          <line x1={PAD.l} x2={W - PAD.r} y1={yToPx(y)} y2={yToPx(y)} stroke="rgba(255,255,255,0.07)" />
          <text x={PAD.l - 8} y={yToPx(y) + 4} textAnchor="end" fontSize="11" fill="rgba(255,255,255,0.4)" fontFamily="monospace">
            {y}
          </text>
        </g>
      ))}
      {[0.25, 0.5, 0.75, 1].map((x) => (
        <g key={x}>
          <text x={xToPx(x)} y={H - PAD.b + 18} textAnchor="middle" fontSize="11" fill="rgba(255,255,255,0.4)" fontFamily="monospace">
            {x}
          </text>
        </g>
      ))}
      <text x={W - PAD.r} y={H - 8} textAnchor="end" fontSize="12" fill="rgba(255,255,255,0.5)" fontFamily="serif" fontStyle="italic">
        p（正面概率）
      </text>
      <text x={10} y={PAD.t + 4} fontSize="12" fill="rgba(255,255,255,0.5)" fontFamily="serif" fontStyle="italic">
        H(p)
      </text>
      {/* 顶点标注 */}
      <line x1={xToPx(0.5)} x2={xToPx(0.5)} y1={yToPx(1)} y2={H - PAD.b} stroke="rgba(255,255,255,0.15)" strokeDasharray="3 4" />
      <text x={xToPx(0.5)} y={yToPx(1) - 8} textAnchor="middle" fontSize="11" fill="rgba(255,255,255,0.5)">
        最不确定：1 bit
      </text>
      <path d={path} fill="none" stroke="#ffb800" strokeWidth="2.5" />
      <path d={`${path} L${xToPx(1)},${yToPx(0)} L${xToPx(0)},${yToPx(0)} Z`} fill="rgba(255,184,0,0.08)" stroke="none" />
      <line x1={xToPx(p)} x2={xToPx(p)} y1={yToPx(hp)} y2={H - PAD.b} stroke="rgba(255,184,0,0.45)" strokeDasharray="3 4" />
      <circle cx={xToPx(p)} cy={yToPx(hp)} r="7" fill="#ffb800" opacity="0.25" />
      <circle cx={xToPx(p)} cy={yToPx(hp)} r="4.5" fill="#ffb800" />
    </svg>
  );
}

export default function S2Coin() {
  const [pPct, setPPct] = useState(50);
  const p = pPct / 100;
  const [flips, setFlips] = useState<number[]>([]);

  const doFlips = (n: number) => {
    const out: number[] = [];
    for (let i = 0; i < n; i++) out.push(Math.random() < p ? 1 : 0);
    setFlips((prev) => [...prev, ...out].slice(-400));
  };

  const empirical = useMemo(() => {
    if (flips.length === 0) return null;
    const ones = flips.reduce((a, b) => a + b, 0) / flips.length;
    return { pHat: ones, H: entropy([ones, 1 - ones]) };
  }, [flips]);

  return (
    <Section
      id="s2"
      index="02"
      kicker="Entropy"
      title="熵：平均惊讶度"
      lead="单个事件的信息量取决于它的概率，但一个随机「信源」会不断产生各种事件。描述整个信源，我们用期望——把所有可能事件的信息量按概率加权平均，这就是熵（Entropy）。"
    >
      <Reveal>
        <Formula caption="X 的所有取值按概率 p(x) 对信息量 −log₂ p(x) 加权平均">
          H(<M>X</M>) = −Σ <M>p</M>(<M>x</M>) · log<Sub>2</Sub> <M>p</M>(<M>x</M>)
        </Formula>
        <p className="text-center text-sm text-white/50">
          以抛一枚不均匀硬币为例，正面概率为 <M>p</M>，则 H = −<M>p</M>·log₂<M>p</M> − (1−<M>p</M>)·log₂(1−<M>p</M>)
        </p>
      </Reveal>

      <Reveal delay={100}>
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm font-medium text-white/80">调节硬币的「偏心程度」</p>
            <p className="font-mono text-sm text-amber-300">
              p = {fmt(p, 2)} → H = {fmt(binaryEntropy(p), 3)} bit/次
            </p>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            value={pPct}
            onChange={(e) => setPPct(Number(e.target.value))}
            className="slider-amber w-full"
            aria-label="正面概率"
          />
          <div className="mt-4">
            <BinaryCurve p={p} />
          </div>
          <p className="mt-4 text-sm leading-relaxed text-white/55">
            曲线在 p = 0.5 处达到峰值 1 bit——完全公平的硬币最难预测；
            而 p → 0 或 1 时熵趋近 0：结果早已注定，没有任何不确定性。
          </p>
        </div>
      </Reveal>

      <Reveal delay={150}>
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-sm font-medium text-white/80">亲手抛一抛这枚硬币</p>
            <div className="flex gap-2">
              {[1, 10, 100].map((n) => (
                <button
                  key={n}
                  onClick={() => doFlips(n)}
                  className="rounded-full border border-amber-400/40 bg-amber-400/10 px-4 py-1.5 text-sm text-amber-200 transition-all hover:scale-105 hover:bg-amber-400/20 active:scale-95"
                >
                  抛 {n} 次
                </button>
              ))}
              <button
                onClick={() => setFlips([])}
                className="rounded-full border border-white/15 px-4 py-1.5 text-sm text-white/50 transition-colors hover:text-white/80"
              >
                清空
              </button>
            </div>
          </div>

          <div className="mt-5 flex min-h-[44px] flex-wrap gap-1.5">
            {flips.length === 0 && <p className="text-sm text-white/30">结果会显示在这里（正 = 1，反 = 0）</p>}
            {flips.map((f, i) => (
              <span
                key={i}
                className={`flex h-7 w-7 items-center justify-center rounded-md font-mono text-xs ${
                  f === 1 ? 'bg-amber-400/20 text-amber-300' : 'bg-white/[0.06] text-white/45'
                }`}
              >
                {f}
              </span>
            ))}
          </div>

          {empirical && (
            <p className="mt-4 font-mono text-sm text-white/60">
              已抛 {flips.length} 次：经验频率 p̂ = {fmt(empirical.pHat, 3)}，经验熵 ≈ {fmt(empirical.H, 3)} bit
              <span className="text-white/35">（次数越多，越接近理论值 {fmt(binaryEntropy(p), 3)}）</span>
            </p>
          )}
        </div>
      </Reveal>
    </Section>
  );
}
