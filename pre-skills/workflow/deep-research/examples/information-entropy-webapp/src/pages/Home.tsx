import { useEffect, useState } from 'react';
import Hero from '@/sections/Hero';
import S1Surprise from '@/sections/S1Surprise';
import S2Coin from '@/sections/S2Coin';
import S3Distribution from '@/sections/S3Distribution';
import S4Derivation from '@/sections/S4Derivation';
import S5Conditional from '@/sections/S5Conditional';
import S6CrossEntropy from '@/sections/S6CrossEntropy';
import S7Compression from '@/sections/S7Compression';
import S8LLM from '@/sections/S8LLM';

const TOC = [
  { id: 's1', label: '信息量' },
  { id: 's2', label: '熵' },
  { id: 's3', label: '分布实验' },
  { id: 's4', label: '公式推导' },
  { id: 's5', label: '条件熵' },
  { id: 's6', label: '交叉熵' },
  { id: 's7', label: '压缩极限' },
  { id: 's8', label: '大模型' },
];

function TopNav() {
  const [progress, setProgress] = useState(0);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => {
      const doc = document.documentElement;
      const max = doc.scrollHeight - doc.clientHeight;
      setProgress(max > 0 ? window.scrollY / max : 0);
      setScrolled(window.scrollY > 40);
    };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <nav
      className={`fixed inset-x-0 top-0 z-50 transition-all duration-500 ${
        scrolled ? 'bg-black/70 backdrop-blur-md' : 'bg-transparent'
      }`}
    >
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3.5">
        <a href="#" className="font-mono text-sm tracking-widest text-white/85">
          H(X) <span className="text-amber-400">=</span> −Σp·log₂p
        </a>
        <div className="hidden items-center gap-5 md:flex">
          {TOC.map((t) => (
            <a
              key={t.id}
              href={`#${t.id}`}
              className="text-xs text-white/50 transition-colors hover:text-amber-300"
            >
              {t.label}
            </a>
          ))}
        </div>
      </div>
      <div className="h-px w-full bg-white/10">
        <div
          className="h-full bg-gradient-to-r from-amber-500 to-amber-300 transition-[width] duration-150"
          style={{ width: `${progress * 100}%` }}
        />
      </div>
    </nav>
  );
}

function Footer() {
  return (
    <footer className="border-t border-white/10 px-6 py-12 text-center">
      <p className="font-mono text-sm text-white/40">H(X) = −Σ p(x)·log₂ p(x)</p>
      <p className="mt-3 text-xs leading-relaxed text-white/30">
        参考：C. E. Shannon, “A Mathematical Theory of Communication”, 1948 ·
        Cover & Thomas, Elements of Information Theory
      </p>
      <p className="mt-4 text-xs text-white/25">交互式信息论讲义 · 所有计算均在你的浏览器中实时完成</p>
    </footer>
  );
}

export default function Home() {
  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white antialiased">
      <TopNav />
      <Hero />
      <main className="relative">
        {/* 章节间微妙的背景交替 */}
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(255,140,0,0.04),transparent_50%)]" />
        <S1Surprise />
        <div className="bg-white/[0.015]"><S2Coin /></div>
        <S3Distribution />
        <div className="bg-white/[0.015]"><S4Derivation /></div>
        <S5Conditional />
        <div className="bg-white/[0.015]"><S6CrossEntropy /></div>
        <S7Compression />
        <div className="bg-white/[0.015]"><S8LLM /></div>
      </main>
      <Footer />
    </div>
  );
}
