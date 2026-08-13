import { useMemo, useState } from 'react';
import Section from '@/components/Section';
import Reveal from '@/components/Reveal';
import { Formula, M } from '@/components/Math';
import { entropy, fmt } from '@/lib/entropy';

const PX = [0.7, 0.3]; // 晴, 雨
const PY = [0.7, 0.3]; // 不带伞, 带伞

export default function S5Conditional() {
  const [corr, setCorr] = useState(80); // 相关性 0-100
  const c = corr / 100;

  const joint = useMemo(() => {
    // J = (1-c)·独立 + c·完全相关（对角）
    const J = PX.map((px, i) =>
      PY.map((py, j) => (1 - c) * px * py + (i === j ? c * px : 0)),
    );
    return J;
  }, [c]);

  const flat = joint.flat();
  const HXY = entropy(flat);
  const HX = entropy(PX);
  const HY = entropy(PY);
  const HXgY = HXY - HY;
  const HYgX = HXY - HX;
  const MI = HX - HXgY;

  const xLabels = ['晴', '雨'];
  const yLabels = ['不带伞', '带伞'];

  return (
    <Section
      id="s5"
      index="05"
      kicker="Conditional Entropy"
      title="条件熵与互信息"
      lead="现实中的随机变量很少孤立存在。知道一个变量后，另一个变量还剩多少不确定性？这就是条件熵；而它「消灭」掉的那部分不确定性，就是两个变量共享的信息——互信息。"
    >
      <Reveal>
        <div className="grid gap-4 md:grid-cols-2">
          <Formula caption="已知 Y 后 X 的剩余不确定性">
            H(<M>X</M>|<M>Y</M>) = Σ <M>p</M>(<M>y</M>)·H(<M>X</M>|<M>Y</M>=<M>y</M>)
          </Formula>
          <Formula caption="链式法则：联合熵可以分步计算">
            H(<M>X</M>,<M>Y</M>) = H(<M>Y</M>) + H(<M>X</M>|<M>Y</M>)
          </Formula>
        </div>
        <p className="text-center font-serif text-lg italic text-amber-100/90">
          I(<M>X</M>;<M>Y</M>) = H(<M>X</M>) − H(<M>X</M>|<M>Y</M>)
          <span className="ml-3 font-sans text-sm not-italic text-white/45">（互信息 = 被 Y 消除的不确定性）</span>
        </p>
      </Reveal>

      <Reveal delay={100}>
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm font-medium text-white/80">天气（X）与带伞（Y）的相关程度</p>
            <p className="font-mono text-sm text-amber-300">相关强度 = {corr}%</p>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            value={corr}
            onChange={(e) => setCorr(Number(e.target.value))}
            className="slider-amber w-full"
          />

          <div className="mt-6 grid items-center gap-8 md:grid-cols-2">
            {/* 联合分布表 */}
            <div>
              <p className="mb-3 text-xs text-white/45">联合分布 p(x, y)</p>
              <table className="w-full border-collapse text-center font-mono text-sm">
                <thead>
                  <tr className="text-white/45">
                    <th className="p-2 text-xs font-normal">X \ Y</th>
                    {yLabels.map((y) => (
                      <th key={y} className="p-2 font-normal">{y}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {joint.map((row, i) => (
                    <tr key={i}>
                      <td className="p-2 text-white/45">{xLabels[i]}</td>
                      {row.map((v, j) => (
                        <td key={j} className="p-1">
                          <div
                            className="rounded-lg border border-white/10 py-2.5 transition-all duration-200"
                            style={{ background: `rgba(255,184,0,${0.06 + v * 0.9})` }}
                          >
                            <span className={v > 0.25 ? 'text-black/85 font-bold' : 'text-white/80'}>{fmt(v, 3)}</span>
                          </div>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* 熵关系图 */}
            <div>
              <svg viewBox="0 0 320 210" className="mx-auto w-full max-w-sm">
                <circle cx="120" cy="105" r="72" fill="rgba(255,184,0,0.10)" stroke="#ffb800" strokeOpacity="0.7" />
                <circle cx="200" cy="105" r="72" fill="rgba(255,255,255,0.05)" stroke="rgba(255,255,255,0.5)" />
                <text x="80" y="105" textAnchor="middle" fontSize="12" fill="#ffd166">H(X|Y)</text>
                <text x="80" y="122" textAnchor="middle" fontSize="13" fill="#ffd166" fontFamily="monospace">{fmt(HXgY, 3)}</text>
                <text x="160" y="105" textAnchor="middle" fontSize="12" fill="rgba(255,255,255,0.85)">I(X;Y)</text>
                <text x="160" y="122" textAnchor="middle" fontSize="13" fill="rgba(255,255,255,0.85)" fontFamily="monospace">{fmt(MI, 3)}</text>
                <text x="240" y="105" textAnchor="middle" fontSize="12" fill="rgba(255,255,255,0.6)">H(Y|X)</text>
                <text x="240" y="122" textAnchor="middle" fontSize="13" fill="rgba(255,255,255,0.6)" fontFamily="monospace">{fmt(HYgX, 3)}</text>
                <text x="92" y="18" textAnchor="middle" fontSize="12" fill="rgba(255,255,255,0.55)">H(X) = {fmt(HX, 3)}</text>
                <text x="232" y="18" textAnchor="middle" fontSize="12" fill="rgba(255,255,255,0.55)">H(Y) = {fmt(HY, 3)}</text>
              </svg>
              <p className="text-center text-xs text-white/40">
                联合熵 H(X,Y) = <span className="font-mono text-amber-200">{fmt(HXY, 3)}</span> bit
              </p>
            </div>
          </div>

          <p className="mt-6 text-sm leading-relaxed text-white/55">
            把滑块推到 100%：天气完全决定带伞与否，知道 Y 后 X 的不确定性归零，互信息达到最大；
            推到 0：两者独立，知道 Y 对你猜天气毫无帮助，I(X;Y) = 0。
            <strong className="text-white/85">互信息就是「相关性」的信息论度量</strong>——它不假设线性，能捕捉任意统计依赖。
          </p>
        </div>
      </Reveal>

      <Reveal delay={120}>
        <div className="rounded-xl border-l-2 border-amber-400/60 bg-amber-400/[0.06] px-5 py-4 text-sm leading-relaxed text-white/70">
          记住这条不对称：<M>H(X|Y)</M> 与 <M>H(Y|X)</M> 通常不相等，但互信息是对称的：I(<M>X</M>;<M>Y</M>) = I(<M>Y</M>;<M>X</M>)。
          另外总有 0 ≤ H(<M>X</M>|<M>Y</M>) ≤ H(<M>X</M>)——「信息从不增加不确定性」（对平均而言）。
        </div>
      </Reveal>
    </Section>
  );
}
