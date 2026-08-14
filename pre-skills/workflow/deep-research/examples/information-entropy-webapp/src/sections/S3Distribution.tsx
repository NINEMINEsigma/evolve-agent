import { useCallback, useRef, useState } from 'react';
import Section from '@/components/Section';
import Reveal from '@/components/Reveal';
import { M } from '@/components/Math';
import { entropy, normalize, fmt } from '@/lib/entropy';

const LABELS = ['A', 'B', 'C', 'D'];
const W = 620;
const H = 320;
const PAD = { l: 46, r: 16, t: 26, b: 40 };

/** 可拖拽的概率分布编辑器 */
function DistributionEditor() {
  const [weights, setWeights] = useState<number[]>([1, 1, 1, 1]);
  const svgRef = useRef<SVGSVGElement>(null);
  const dragIdx = useRef<number | null>(null);

  const ps = normalize(weights);
  const ent = entropy(ps);
  const maxEnt = Math.log2(4);

  const barW = (W - PAD.l - PAD.r) / 4;
  const yToPx = (y: number) => H - PAD.b - y * (H - PAD.t - PAD.b);

  const handleMove = useCallback(
    (clientY: number) => {
      const svg = svgRef.current;
      if (svg === null || dragIdx.current === null) return;
      const rect = svg.getBoundingClientRect();
      const yPx = ((clientY - rect.top) / rect.height) * H;
      const frac = Math.min(Math.max((H - PAD.b - yPx) / (H - PAD.t - PAD.b), 0.01), 1);
      setWeights((prev) => prev.map((w, i) => (i === dragIdx.current ? frac : w)));
    },
    [],
  );

  const onPointerDown = (i: number) => (e: React.PointerEvent) => {
    dragIdx.current = i;
    (e.target as Element).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (dragIdx.current !== null) handleMove(e.clientY);
  };
  const onPointerUp = () => {
    dragIdx.current = null;
  };

  return (
    <div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full touch-none select-none"
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
      >
        {[0.25, 0.5, 0.75, 1].map((y) => (
          <g key={y}>
            <line x1={PAD.l} x2={W - PAD.r} y1={yToPx(y)} y2={yToPx(y)} stroke="rgba(255,255,255,0.07)" />
            <text x={PAD.l - 8} y={yToPx(y) + 4} textAnchor="end" fontSize="11" fill="rgba(255,255,255,0.4)" fontFamily="monospace">
              {y}
            </text>
          </g>
        ))}
        {ps.map((p, i) => {
          const x = PAD.l + i * barW + barW * 0.15;
          const bw = barW * 0.7;
          const yTop = yToPx(p);
          return (
            <g key={i} className="cursor-ns-resize" onPointerDown={onPointerDown(i)}>
              {/* 宽阔的隐形命中区 */}
              <rect x={PAD.l + i * barW} y={PAD.t} width={barW} height={H - PAD.t - PAD.b} fill="transparent" />
              <rect
                x={x}
                y={yTop}
                width={bw}
                height={H - PAD.b - yTop}
                rx={6}
                fill={dragIdx.current === i ? 'rgba(255,184,0,0.85)' : 'rgba(255,184,0,0.45)'}
                stroke="#ffb800"
                strokeOpacity={0.8}
                strokeWidth={1}
              />
              {/* 顶部把手 */}
              <rect x={x + bw / 2 - 18} y={yTop - 12} width={36} height={7} rx={3.5} fill="#ffb800" />
              <text x={x + bw / 2} y={Math.max(yTop - 20, PAD.t - 4)} textAnchor="middle" fontSize="13" fill="#ffd166" fontFamily="monospace">
                {fmt(p, 3)}
              </text>
              <text x={x + bw / 2} y={H - PAD.b + 22} textAnchor="middle" fontSize="14" fill="rgba(255,255,255,0.75)" fontFamily="serif" fontStyle="italic">
                {LABELS[i]}
              </text>
            </g>
          );
        })}
        <text x={12} y={PAD.t} fontSize="12" fill="rgba(255,255,255,0.5)" fontFamily="serif" fontStyle="italic">
          p(x)
        </text>
      </svg>

      {/* 各项贡献分解 */}
      <div className="mt-6">
        <p className="mb-2 text-xs text-white/45">每一项对熵的贡献 −p(x)·log₂p(x)：</p>
        <div className="flex h-9 w-full overflow-hidden rounded-lg border border-white/10">
          {ps.map((p, i) => {
            const c = p > 1e-9 ? -p * Math.log2(p) : 0;
            const frac = ent > 1e-9 ? c / ent : 0.25;
            return (
              <div
                key={i}
                className="flex items-center justify-center text-xs font-medium text-black/80 transition-all duration-300"
                style={{
                  width: `${frac * 100}%`,
                  background: `rgba(255, ${184 - i * 18}, ${i * 30}, ${0.85 - i * 0.12})`,
                }}
                title={`${LABELS[i]}: ${fmt(c, 3)} bit`}
              >
                {frac > 0.07 && `${LABELS[i]} ${fmt(c, 2)}`}
              </div>
            );
          })}
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
        <p className="font-mono text-lg text-white/85">
          H(X) = <span className="font-bold text-amber-300">{fmt(ent, 3)}</span> bit
          <span className="ml-3 text-sm text-white/40">上限 log₂4 = 2 bit</span>
        </p>
        <div className="flex gap-2">
          <button
            onClick={() => setWeights([1, 1, 1, 1])}
            className="rounded-full border border-white/15 px-4 py-1.5 text-sm text-white/60 transition-colors hover:border-amber-400/50 hover:text-amber-200"
          >
            均匀分布
          </button>
          <button
            onClick={() => setWeights([0.97, 0.01, 0.01, 0.01])}
            className="rounded-full border border-white/15 px-4 py-1.5 text-sm text-white/60 transition-colors hover:border-amber-400/50 hover:text-amber-200"
          >
            极度偏斜
          </button>
        </div>
      </div>

      {/* 熵进度条 */}
      <div className="mt-3 h-2.5 w-full overflow-hidden rounded-full bg-white/[0.07]">
        <div
          className="h-full rounded-full bg-gradient-to-r from-amber-500 to-amber-300 transition-all duration-300"
          style={{ width: `${(ent / maxEnt) * 100}%` }}
        />
      </div>
    </div>
  );
}

export default function S3Distribution() {
  return (
    <Section
      id="s3"
      index="03"
      kicker="Playground"
      title="亲手捏一个分布"
      lead="熵公式适用于任意离散分布。下面是一个四面骰子的概率分布编辑器：直接拖动柱子改变概率（会自动归一化），观察熵如何随分布形状变化。"
    >
      <Reveal>
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
          <DistributionEditor />
        </div>
      </Reveal>

      <Reveal delay={100}>
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
            <p className="mb-2 font-mono text-xs uppercase tracking-widest text-amber-400/80">观察 1</p>
            <p className="text-sm leading-relaxed text-white/65">
              分布越均匀，熵越大。四个事件等概率时达到最大值 log₂4 = 2 bit——这时你最「猜不透」结果。
            </p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
            <p className="mb-2 font-mono text-xs uppercase tracking-widest text-amber-400/80">观察 2</p>
            <p className="text-sm leading-relaxed text-white/65">
              某个事件概率趋近 1 时，熵趋近 0。结果几乎注定，信源不再带来新信息。
            </p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
            <p className="mb-2 font-mono text-xs uppercase tracking-widest text-amber-400/80">观察 3</p>
            <p className="text-sm leading-relaxed text-white/65">
              概率小的事件单独看信息量（−log₂<M>p</M>）很大，但它很少发生，对总熵的贡献 <M>p</M>·(−log₂<M>p</M>) 仍然有限。
            </p>
          </div>
        </div>
      </Reveal>

      <Reveal delay={150}>
        <div className="rounded-xl border-l-2 border-amber-400/60 bg-amber-400/[0.06] px-5 py-4 text-sm leading-relaxed text-white/70">
          一个严谨的事实：<M>n</M> 个事件的分布在均匀时熵最大，为 log₂<M>n</M>。
          证明用 Jensen 不等式或拉格朗日乘子法即可得到。直观地说——<strong className="text-white/90">均匀即无知，无知即最大的不确定性。</strong>
        </div>
      </Reveal>

      <Reveal delay={50}>
        <p className="text-xs text-white/30">
          注：拖动时各柱保持相对比例并整体归一化；公式中的求和约定 0·log0 = 0（由极限 x·logx → 0 定义）。
        </p>
      </Reveal>
    </Section>
  );
}
