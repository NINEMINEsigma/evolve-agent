import { useMemo, useState, type ReactNode } from 'react';
import Section from '@/components/Section';
import Reveal from '@/components/Reveal';
import { Formula } from '@/components/Math';
import { entropy, softmaxTemp, fmt } from '@/lib/entropy';

/* ---------- 交互 1：下一词预测的损失 ---------- */

const CONTEXT = '北京的冬天特别___';
const CANDIDATES = [
  { token: '冷', q: 0.52 },
  { token: '干', q: 0.18 },
  { token: '长', q: 0.11 },
  { token: '安静', q: 0.07 },
  { token: '美', q: 0.05 },
  { token: '热', q: 0.02 },
  { token: '短', q: 0.02 },
  { token: '湿', q: 0.01 },
  { token: '早', q: 0.01 },
  { token: '亮', q: 0.01 },
];

function NextTokenDemo() {
  const [picked, setPicked] = useState<number | null>(null);

  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
      <p className="mb-1 text-sm font-medium text-white/80">扮演语料库：选出「真实文本里」的下一个词</p>
      <p className="mb-4 text-xs text-white/40">
        模型对它看到的每个真实词汇都要「交学费」：损失 = −ln q（真实词）。q 越小，学费越贵。
      </p>
      <p className="mb-4 rounded-lg bg-white/[0.04] px-4 py-3 font-mono text-sm text-white/80">
        {CONTEXT}
        <span className={picked !== null ? 'font-bold text-amber-300' : 'text-white/30'}>
          {picked !== null ? CANDIDATES[picked].token : '？？'}
        </span>
      </p>
      <div className="flex flex-wrap gap-2">
        {CANDIDATES.map((c, i) => (
          <button
            key={c.token}
            onClick={() => setPicked(i)}
            className={`rounded-full border px-4 py-2 text-sm transition-all hover:scale-105 active:scale-95 ${
              picked === i
                ? 'border-amber-400 bg-amber-400/20 text-amber-200'
                : 'border-white/15 text-white/60 hover:border-amber-400/40 hover:text-amber-100'
            }`}
          >
            {c.token}
            <span className="ml-1.5 font-mono text-[10px] opacity-60">{fmt(c.q, 2)}</span>
          </button>
        ))}
      </div>
      {picked !== null && (
        <div className="mt-5 grid gap-3 rounded-xl bg-white/[0.03] p-4 font-mono text-sm text-white/70 md:grid-cols-3">
          <div>
            该词概率 q = <b className="text-amber-300">{fmt(CANDIDATES[picked].q, 2)}</b>
          </div>
          <div>
            损失 −ln q = <b className="text-amber-300">{fmt(-Math.log(CANDIDATES[picked].q), 3)}</b> nat
          </div>
          <div>
            等效困惑度 1/q = <b className="text-amber-300">{fmt(1 / CANDIDATES[picked].q, 1)}</b>
          </div>
        </div>
      )}
      <p className="mt-4 text-sm leading-relaxed text-white/55">
        万亿 token 的训练语料 × 每个位置都这样算一次 −ln q，再求平均——
        这就是大模型训练时 TensorFlow / PyTorch 里那行 <span className="font-mono text-amber-200/90">cross_entropy_loss</span> 的全部含义。
      </p>
    </div>
  );
}

/* ---------- 交互 2：温度采样 ---------- */

const SAMPLING_TOKENS = [
  { token: '冷', logit: 3.2 },
  { token: '干', logit: 2.4 },
  { token: '长', logit: 2.1 },
  { token: '安静', logit: 1.7 },
  { token: '美', logit: 1.5 },
  { token: '热', logit: 0.9 },
];

function TemperatureDemo() {
  const [T, setT] = useState(100); // 1.00
  const [sampled, setSampled] = useState<number | null>(null);
  const [history, setHistory] = useState<number[]>([]);

  const probs = useMemo(() => softmaxTemp(SAMPLING_TOKENS.map((t) => t.logit), T / 100), [T]);
  const ent = entropy(probs);
  const maxEnt = Math.log2(SAMPLING_TOKENS.length);

  const doSample = () => {
    const r = Math.random();
    let acc = 0;
    let idx = probs.length - 1;
    for (let i = 0; i < probs.length; i++) {
      acc += probs[i];
      if (r < acc) {
        idx = i;
        break;
      }
    }
    setSampled(idx);
    setHistory((h) => [...h, idx].slice(-24));
  };

  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm font-medium text-white/80">温度 T：给输出分布「加热」或「冷却」</p>
        <p className="font-mono text-sm text-amber-300">T = {fmt(T / 100, 2)}</p>
      </div>
      <input
        type="range"
        min={10}
        max={250}
        value={T}
        onChange={(e) => setT(Number(e.target.value))}
        className="slider-amber w-full"
      />
      <div className="mt-1 flex justify-between font-mono text-[11px] text-white/35">
        <span>T→0：锐化，几乎总选最优词（低熵）</span>
        <span>T→∞：摊平，接近均匀乱选（高熵）</span>
      </div>

      <div className="mt-6 space-y-2.5">
        {SAMPLING_TOKENS.map((t, i) => (
          <div key={t.token} className="flex items-center gap-3">
            <span className={`w-10 text-right text-sm ${sampled === i ? 'font-bold text-amber-300' : 'text-white/75'}`}>
              {t.token}
            </span>
            <div className="relative h-6 flex-1 overflow-hidden rounded-md bg-white/[0.05]">
              <div
                className={`h-full rounded-md transition-all duration-300 ${
                  sampled === i ? 'bg-gradient-to-r from-amber-400 to-amber-300' : 'bg-amber-500/35'
                }`}
                style={{ width: `${probs[i] * 100}%` }}
              />
            </div>
            <span className="w-16 font-mono text-xs text-white/55">{(probs[i] * 100).toFixed(1)}%</span>
          </div>
        ))}
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-4">
        <button
          onClick={doSample}
          className="rounded-full border border-amber-400/40 bg-amber-400/10 px-5 py-2 text-sm text-amber-200 transition-all hover:scale-105 hover:bg-amber-400/20 active:scale-95"
        >
          按当前分布采样一个词
        </button>
        <p className="font-mono text-sm text-white/60">
          输出分布的熵 H = <b className="text-amber-300">{fmt(ent, 3)}</b> / {fmt(maxEnt, 3)} bit
        </p>
      </div>

      {history.length > 0 && (
        <p className="mt-3 break-words font-mono text-sm leading-7 text-white/70">
          采样序列：
          {history.map((h, i) => (
            <span
              key={i}
              className={`mx-0.5 rounded px-1.5 py-0.5 ${
                i === history.length - 1 ? 'bg-amber-400/25 text-amber-200' : 'bg-white/[0.05] text-white/55'
              }`}
            >
              {SAMPLING_TOKENS[h].token}
            </span>
          ))}
        </p>
      )}
      <p className="mt-4 text-sm leading-relaxed text-white/55">
        温度参数的数学形式就是 softmax(zᵢ/T)：T 直接缩放输出分布的熵。
        你在大模型产品里调的「创造性 / 严谨性」开关，调的就是信息熵。
      </p>
    </div>
  );
}

/* ---------- 主章节 ---------- */

export default function S8LLM() {
  return (
    <Section
      id="s8"
      index="08"
      kicker="Large Language Models"
      title="终点与起点：大模型里的熵"
      lead="回到今天。GPT、Claude、Kimi 这样的语言模型只做一件事：给定上文，输出下一个 token 的概率分布 Q。而衡量它做得好坏、指导它训练、控制它生成的每一颗螺丝，都是信息论在 1948 年就铸好的。"
    >
      <Reveal>
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
            <p className="font-mono text-xs uppercase tracking-widest text-amber-400/80">训练</p>
            <p className="mt-2 text-sm leading-relaxed text-white/65">
              目标：让模型分布 Q 逼近真实语言分布 P。
              损失函数 = 交叉熵 H(P, Q)。由于 H(P) 是定值，
              最小化交叉熵 ⟺ 最小化 D_KL(P∥Q)。
            </p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
            <p className="font-mono text-xs uppercase tracking-widest text-amber-400/80">评估</p>
            <p className="mt-2 text-sm leading-relaxed text-white/65">
              困惑度（Perplexity）= e^(平均每 token 交叉熵)，
              直观含义是「模型每写一词，平均像在多少个等可能选项中犹豫」。
              越低，模型越笃定。
            </p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
            <p className="font-mono text-xs uppercase tracking-widest text-amber-400/80">生成</p>
            <p className="mt-2 text-sm leading-relaxed text-white/65">
              采样温度 T 直接操纵输出分布的熵：
              低温收敛、高温发散。所谓「模型幻觉」，
              往往就是高熵区域里一次不幸的采样。
            </p>
          </div>
        </div>
      </Reveal>

      <Reveal delay={80}>
        <NextTokenDemo />
      </Reveal>

      <Reveal delay={80}>
        <TemperatureDemo />
      </Reveal>

      <Reveal delay={100}>
        <Formula caption="困惑度 = 平均交叉熵的指数化，又称「等效分支因子」">
          PPL = e<Sup>−(1/N)·Σ ln q(xᵢ)</Sup> = 2<Sup>H(P,Q)</Sup>
        </Formula>
      </Reveal>

      <Reveal delay={120}>
        <div className="rounded-2xl border border-amber-400/25 bg-gradient-to-b from-amber-400/[0.08] to-transparent p-8">
          <p className="mb-6 font-mono text-xs uppercase tracking-[0.3em] text-amber-400/80">总结 · 一条贯穿 78 年的线</p>
          <ol className="space-y-5">
            {[
              ['1948', '香农定义熵 H = −Σp·log p，证明它是压缩的极限、信息的体积。'],
              ['1951', '香农本人用「猜下一个字母」的游戏估算出英文的熵约为每字母 0.6–1.3 bit——这本质上就是最早的语言模型实验。'],
              ['今天', '大模型把同一个游戏做到了极致：预测下一个 token，用交叉熵损失训练，用困惑度打分。模型规模与数据的增长（Scaling Law），本质上是在持续压低交叉熵，逼近人类语言本身的熵这个不可逾越的下限。'],
              ['同一件事', '预测与压缩是同一枚硬币：对下一个词猜得越准，就能用越短的编码写下整段文本。一个足够好的语言模型，就是人类语言的通用压缩器——这大概是香农未曾预料、却乐见其成的结局。'],
            ].map(([t, body]) => (
              <li key={t} className="flex gap-4">
                <span className="mt-0.5 w-16 shrink-0 font-mono text-sm font-bold text-amber-300">{t}</span>
                <p className="text-sm leading-relaxed text-white/70 md:text-base">{body}</p>
              </li>
            ))}
          </ol>
          <p className="mt-8 border-t border-white/10 pt-6 text-center font-serif text-xl italic text-amber-100/90 md:text-2xl">
            “We communicate by reducing uncertainty —<br className="md:hidden" /> and now, so do machines.”
          </p>
        </div>
      </Reveal>
    </Section>
  );
}

function Sup({ children }: { children: ReactNode }) {
  return <sup className="text-[0.6em] not-italic">{children}</sup>;
}
