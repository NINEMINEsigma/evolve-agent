import { useState } from 'react';
import Section from '@/components/Section';
import Reveal from '@/components/Reveal';
import { Formula, M, Sub } from '@/components/Math';
import { crossEntropy, entropy, klDivergence, normalize, fmt } from '@/lib/entropy';

const LABELS = ['的', '是', '在', '猫'];
const P = [0.5, 0.25, 0.15, 0.1]; // 真实分布

const PRESETS: { name: string; w: number[] }[] = [
  { name: '完美复刻', w: [...P] },
  { name: '大致靠谱', w: [0.4, 0.3, 0.2, 0.1] },
  { name: '均匀乱猜', w: [1, 1, 1, 1] },
  { name: '完全颠倒', w: [0.1, 0.15, 0.25, 0.5] },
];

export default function S6CrossEntropy() {
  const [weights, setWeights] = useState<number[]>([0.4, 0.3, 0.2, 0.1]);
  const q = normalize(weights);

  const HP = entropy(P);
  const HPQ = crossEntropy(P, q);
  const DKL = klDivergence(P, q);

  const setW = (i: number, v: number) => setWeights((prev) => prev.map((x, j) => (j === i ? v : x)));

  const maxBar = 0.55;

  return (
    <Section
      id="s6"
      index="06"
      kicker="Cross-Entropy & KL"
      title="交叉熵与 KL 散度"
      lead="当世界服从真实分布 P，而你头脑里（或你的模型里）装着分布 Q，会发生什么？交叉熵回答「用 Q 的视角为 P 的世界编码，平均要付多少代价」；KL 散度则是这份代价中「本来可以避免」的部分——两者之差恰好是熵本身。这组关系是从信息论通往机器学习的桥。"
    >
      <Reveal>
        <Formula caption="交叉熵 = 真实熵 + 模型与现实的差距（Gibbs 不等式保证 D_KL ≥ 0）">
          H(<M>P</M>,<M>Q</M>) = H(<M>P</M>) + D<Sub>KL</Sub>(<M>P</M> ∥ <M>Q</M>)
        </Formula>
      </Reveal>

      <Reveal delay={100}>
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
          <p className="mb-1 text-sm font-medium text-white/80">
            场景：一段文本里四个字的真实频率是 P（白框）；调节你的「语言模型」Q（琥珀柱）去逼近它
          </p>
          <p className="mb-5 text-xs text-white/40">拖动每根柱子调整 Q 中该字的概率（自动归一化）</p>

          <div className="grid gap-5 md:grid-cols-2">
            {LABELS.map((lb, i) => (
              <div key={lb} className="rounded-xl bg-white/[0.03] p-4">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-lg font-bold text-white/90">「{lb}」</span>
                  <span className="font-mono text-xs text-white/50">
                    P = {fmt(P[i], 2)} · Q = {fmt(q[i], 3)}
                  </span>
                </div>
                {/* P vs Q 对比条 */}
                <div className="relative mb-3 h-8">
                  <div
                    className="absolute inset-y-0 left-0 rounded-md border border-white/50"
                    style={{ width: `${(P[i] / maxBar) * 100}%` }}
                  />
                  <div
                    className="absolute inset-y-0 left-0 rounded-md bg-gradient-to-r from-amber-500/80 to-amber-300/80 transition-all duration-200"
                    style={{ width: `${(q[i] / maxBar) * 100}%` }}
                  />
                </div>
                <input
                  type="range"
                  min={1}
                  max={100}
                  value={Math.round(weights[i] * 100)}
                  onChange={(e) => setW(i, Number(e.target.value) / 100)}
                  className="slider-amber w-full"
                />
              </div>
            ))}
          </div>

          <div className="mt-5 flex flex-wrap gap-2">
            {PRESETS.map((pr) => (
              <button
                key={pr.name}
                onClick={() => setWeights([...pr.w])}
                className="rounded-full border border-white/15 px-4 py-1.5 text-sm text-white/60 transition-all hover:scale-105 hover:border-amber-400/50 hover:text-amber-200 active:scale-95"
              >
                {pr.name}
              </button>
            ))}
          </div>

          {/* 分解条 */}
          <div className="mt-8">
            <div className="flex h-12 w-full overflow-hidden rounded-xl border border-white/10">
              <div
                className="flex items-center justify-center bg-amber-400/80 text-sm font-bold text-black/85 transition-all duration-300"
                style={{ width: `${(HP / HPQ) * 100}%` }}
              >
                H(P) = {fmt(HP, 3)}
              </div>
              <div
                className="flex items-center justify-center bg-red-400/25 text-sm text-red-200 transition-all duration-300"
                style={{ width: `${(DKL / Math.max(HPQ, 1e-9)) * 100}%` }}
              >
                {DKL / Math.max(HPQ, 1e-9) > 0.08 && `D_KL = ${fmt(DKL, 3)}`}
              </div>
            </div>
            <div className="mt-3 flex flex-wrap justify-between font-mono text-sm text-white/60">
              <span>
                交叉熵 H(P,Q) = <b className="text-amber-300">{fmt(HPQ, 3)}</b> bit
              </span>
              <span>
                浪费的部分 D_KL(P∥Q) = <b className="text-red-300">{fmt(DKL, 3)}</b> bit
              </span>
            </div>
          </div>

          <p className="mt-5 text-sm leading-relaxed text-white/55">
            试试「完美复刻」：D_KL 归零，交叉熵触底等于 H(P)——这是任何模型都无法突破的下限。
            再试「完全颠倒」：模型把高概率押在罕见字上，D_KL 暴涨。
            <strong className="text-white/85">训练模型的本质，就是不断压低 D_KL，让 Q 向 P 靠拢。</strong>
          </p>
        </div>
      </Reveal>

      <Reveal delay={120}>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
            <p className="mb-2 font-mono text-xs uppercase tracking-widest text-amber-400/80">注意方向</p>
            <p className="text-sm leading-relaxed text-white/65">
              KL 散度不对称：D_KL(P∥Q) ≠ D_KL(Q∥P)。机器学习中几乎总是前者——
              用真实数据 P 去考校模型 Q，这叫「前向 KL」。
            </p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
            <p className="mb-2 font-mono text-xs uppercase tracking-widest text-amber-400/80">与互信息的联系</p>
            <p className="text-sm leading-relaxed text-white/65">
              互信息其实就是联合分布与独立假设之间的 KL 散度：I(X;Y) = D_KL( p(x,y) ∥ p(x)p(y) )。
              信息论的概念在这里收拢成一张网。
            </p>
          </div>
        </div>
      </Reveal>
    </Section>
  );
}
