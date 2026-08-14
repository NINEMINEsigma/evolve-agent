import { type ReactNode } from 'react';
import Reveal from './Reveal';

interface SectionProps {
  id: string;
  index: string; // 章节编号，如 "01"
  kicker: string; // 英文小标签
  title: string;
  lead?: string;
  children: ReactNode;
}

export default function Section({ id, index, kicker, title, lead, children }: SectionProps) {
  return (
    <section id={id} className="relative mx-auto max-w-5xl scroll-mt-24 px-6 py-24 md:py-32">
      <Reveal>
        <div className="mb-4 flex items-baseline gap-4">
          <span className="font-mono text-sm tracking-[0.3em] text-amber-400/80">{index}</span>
          <span className="text-xs font-medium uppercase tracking-[0.35em] text-white/40">{kicker}</span>
          <span className="h-px flex-1 bg-gradient-to-r from-amber-400/40 to-transparent" />
        </div>
        <h2 className="text-3xl font-bold tracking-tight text-white/95 md:text-5xl">{title}</h2>
        {lead && <p className="mt-5 max-w-3xl text-base leading-relaxed text-white/60 md:text-lg">{lead}</p>}
      </Reveal>
      <div className="mt-12 space-y-10">{children}</div>
    </section>
  );
}
