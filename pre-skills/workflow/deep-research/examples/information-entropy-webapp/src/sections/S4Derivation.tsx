import { useState } from 'react';
import Section from '@/components/Section';
import Reveal from '@/components/Reveal';
import { surprise, fmt } from '@/lib/entropy';

const AXIOMS = [
  {
    n: 'Ⅰ',
    title: '连续性',
    body: '概率的微小变化只会带来不确定性的微小变化。H 关于 p 连续，不能忽大忽小地跳变。',
  },
  {
    n: 'Ⅱ',
    title: '单调性',
    body: '等概率分布下，可能的结果越多（n 越大），不确定性越大：H(1/n) 关于 n 单调递增。',
  },
  {
    n: 'Ⅲ',
    title: '可加性（链式分解）',
    body: '不确定性可以分步消除：先揭晓粗分类，再揭晓类内细节，总信息量不变。这等价于 h(p·q) = h(p) + h(q)。',
  },
];

export default function S4Derivation() {
  const [p1, setP1] = useState(50);
  const [p2, setP2] = useState(25);
  const pa = Math.max(p1 / 100, 0.01);
  const pb = Math.max(p2 / 100, 0.01);

  return (
    <Section
      id="s4"
      index="04"
      kicker="Derivation"
      title="为什么偏偏是这个公式"
      lead="熵公式不是香农拍脑袋发明的。他先写下三条任何「不确定性的合理度量」都必须满足的公理，然后证明了：满足这三条的函数，在相差一个常数倍的意义下只有 −Σp·log p 这一个。"
    >
      <Reveal>
        <div className="grid gap-4 md:grid-cols-3">
          {AXIOMS.map((a, i) => (
            <div key={a.n} className="rounded-xl border border-white/10 bg-white/[0.03] p-5" style={{ transitionDelay: `${i * 80}ms` }}>
              <p className="font-serif text-2xl text-amber-300">{a.n}</p>
              <p className="mt-2 font-semibold text-white/90">{a.title}</p>
              <p className="mt-2 text-sm leading-relaxed text-white/60">{a.body}</p>
            </div>
          ))}
        </div>
      </Reveal>

      <Reveal delay={100}>
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6 md:p-8">
          <p className="mb-6 text-sm font-medium uppercase tracking-[0.25em] text-white/40">推导骨架</p>
          <ol className="space-y-6">
            {[
              {
                step: '第 1 步',
                tex: '由可加性：独立事件 A、B 同时发生的信息量 h(pₐ·p_b) = h(pₐ) + h(p_b)。在正实数上满足这条函数方程且连续的函数，只能是对数函数 h(p) = c·log p。',
              },
              {
                step: '第 2 步',
                tex: '由单调性：p 越大应该越「不惊讶」，所以系数 c 必须取负。取 c = −1 并选 2 为底，单位就是 bit：h(p) = −log₂ p。',
              },
              {
                step: '第 3 步',
                tex: '信源每次随机产出事件 xᵢ，长期来看平均信息量就是期望：H = Σ pᵢ·h(pᵢ) = −Σ pᵢ·log₂ pᵢ。',
              },
              {
                step: '第 4 步',
                tex: '香农进一步证明：任何满足三条公理的度量都形如 k·H（k > 0）。也就是说，熵公式是被公理唯一逼出来的，而非众多候选之一。',
              },
            ].map((s) => (
              <li key={s.step} className="flex gap-4">
                <span className="mt-0.5 shrink-0 font-mono text-xs text-amber-400/80">{s.step}</span>
                <p className="text-sm leading-relaxed text-white/70 md:text-base">{s.tex}</p>
              </li>
            ))}
          </ol>
        </div>
      </Reveal>

      <Reveal delay={150}>
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
          <p className="mb-4 text-sm font-medium text-white/80">
            亲手验证可加性：两个独立事件同时发生，信息量正好相加
          </p>
          <div className="grid gap-6 md:grid-cols-2">
            <div>
              <label className="mb-1 flex justify-between font-mono text-xs text-white/50">
                <span>事件 A 概率 pₐ</span>
                <span className="text-amber-300">{fmt(pa, 2)} → {fmt(surprise(pa), 2)} bit</span>
              </label>
              <input type="range" min={1} max={100} value={p1} onChange={(e) => setP1(Number(e.target.value))} className="slider-amber w-full" />
            </div>
            <div>
              <label className="mb-1 flex justify-between font-mono text-xs text-white/50">
                <span>事件 B 概率 p_b</span>
                <span className="text-amber-300">{fmt(pb, 2)} → {fmt(surprise(pb), 2)} bit</span>
              </label>
              <input type="range" min={1} max={100} value={p2} onChange={(e) => setP2(Number(e.target.value))} className="slider-amber w-full" />
            </div>
          </div>
          <div className="mt-6 flex flex-col items-center gap-2 rounded-xl bg-white/[0.03] px-4 py-4 font-mono text-sm text-white/75 md:flex-row md:justify-center md:gap-6">
            <span>h(pₐ·p_b) = −log₂({fmt(pa * pb, 4)}) = <b className="text-amber-300">{fmt(surprise(pa * pb), 3)}</b></span>
            <span className="text-white/30">=</span>
            <span>
              h(pₐ) + h(p_b) = {fmt(surprise(pa), 3)} + {fmt(surprise(pb), 3)} = <b className="text-amber-300">{fmt(surprise(pa) + surprise(pb), 3)}</b>
            </span>
          </div>
          <p className="mt-4 text-center text-xs text-white/40">
            乘法变加法——这正是对数的天性，也是熵公式里那个 log 的全部由来
          </p>
        </div>
      </Reveal>

      <Reveal delay={100}>
        <p className="text-sm leading-relaxed text-white/50">
          延伸阅读：这条唯一性定理常被称为 Shannon–Khinchin 定理（Khinchin 后来给出了更严格的表述）。
          若放弃可加性公理，会得到 Rényi 熵、Tsallis 熵等推广家族，它们在生态学、统计物理中各有用途。
        </p>
      </Reveal>
    </Section>
  );
}
