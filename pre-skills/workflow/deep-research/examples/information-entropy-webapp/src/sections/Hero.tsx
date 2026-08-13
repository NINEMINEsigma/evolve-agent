import { useEffect, useRef } from 'react';

/** 生成式背景：多层琥珀色流动波线 + 漂浮比特字符，振幅随时间调制 */
function FlowCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let raf = 0;
    let w = 0;
    let h = 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    const resize = () => {
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener('resize', resize);

    interface Bit {
      x: number;
      y: number;
      v: number;
      ch: string;
      o: number;
    }
    const bits: Bit[] = Array.from({ length: 46 }, () => ({
      x: Math.random(),
      y: Math.random(),
      v: 0.02 + Math.random() * 0.05,
      ch: Math.random() > 0.5 ? '1' : '0',
      o: 0.05 + Math.random() * 0.16,
    }));

    const LINES = 26;
    const start = performance.now();

    const draw = (now: number) => {
      const t = (now - start) / 1000;
      ctx.clearRect(0, 0, w, h);

      // 流动波线：振幅随位置与时间调制
      for (let i = 0; i < LINES; i++) {
        const fy = (i + 0.5) / LINES;
        const baseY = fy * h;
        const amp = 14 + 30 * Math.sin(t * 0.35 + i * 0.7) ** 2;
        const alpha = 0.05 + 0.16 * Math.sin(i * 1.3 + t * 0.5) ** 2;
        const grad = ctx.createLinearGradient(0, 0, w, 0);
        grad.addColorStop(0, `rgba(255, 140, 0, 0)`);
        grad.addColorStop(0.5, `rgba(255, 184, 0, ${alpha})`);
        grad.addColorStop(1, `rgba(255, 140, 0, 0)`);
        ctx.strokeStyle = grad;
        ctx.lineWidth = 1.1;
        ctx.beginPath();
        for (let x = 0; x <= w; x += 6) {
          const u = x / w;
          const y =
            baseY +
            Math.sin(u * 4.2 + t * 0.7 + i * 0.55) * amp * Math.sin(u * Math.PI) +
            Math.sin(u * 9.5 - t * 0.4 + i) * amp * 0.28 * Math.sin(u * Math.PI);
          if (x === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      // 漂浮比特
      ctx.font = '12px ui-monospace, SFMono-Regular, Menlo, monospace';
      bits.forEach((b) => {
        b.y -= b.v / 100;
        if (b.y < -0.05) {
          b.y = 1.05;
          b.x = Math.random();
          b.ch = Math.random() > 0.5 ? '1' : '0';
        }
        ctx.fillStyle = `rgba(255, 200, 90, ${b.o})`;
        ctx.fillText(b.ch, b.x * w, b.y * h);
      });

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
    };
  }, []);

  return <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-hidden />;
}

export default function Hero() {
  return (
    <header className="relative flex min-h-[100svh] flex-col overflow-hidden">
      <FlowCanvas />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_0%,rgba(10,10,10,0.55)_70%,#0a0a0a_100%)]" />

      <div className="relative z-10 flex flex-1 flex-col items-center justify-center px-6 text-center">
        <p className="mb-6 text-xs font-medium uppercase tracking-[0.5em] text-amber-400/90">
          Information Theory · 1948
        </p>
        <h1 className="max-w-4xl text-5xl font-black leading-[1.08] tracking-tight text-white md:text-7xl">
          信息熵
          <span className="mx-4 inline-block h-3 w-3 rounded-full bg-amber-400 align-middle shadow-[0_0_24px_6px_rgba(255,184,0,0.55)] md:h-4 md:w-4" />
          不确定性的度量
        </h1>
        <p className="mt-8 max-w-2xl text-base leading-relaxed text-white/60 md:text-lg">
          从一次抛硬币的直觉出发，一步步推导香农的熵公式，
          穿过交叉熵与 KL 散度，抵达它今日的归宿——大语言模型的心脏。
        </p>
        <div className="mt-10 flex items-center gap-6 font-mono text-sm text-white/45">
          <span>H(X) = −Σ p·log₂ p</span>
          <span className="hidden h-4 w-px bg-white/20 md:block" />
          <span className="hidden md:block">交互式数学讲义</span>
        </div>
      </div>

      <div className="relative z-10 flex justify-center pb-10">
        <a
          href="#s1"
          className="group flex flex-col items-center gap-3 text-white/40 transition-colors hover:text-amber-300"
        >
          <span className="text-xs tracking-[0.3em]">向下滚动开始</span>
          <span className="block h-10 w-px animate-pulse bg-gradient-to-b from-amber-400 to-transparent" />
        </a>
      </div>
    </header>
  );
}
