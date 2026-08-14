import { type ReactNode } from 'react';

/** 行内数学符号：衬线斜体拉丁字母 */
export function M({ children }: { children: ReactNode }) {
  return <span className="font-serif italic text-white/90">{children}</span>;
}

/** 下标 */
export function Sub({ children }: { children: ReactNode }) {
  return <sub className="text-[0.65em] not-italic">{children}</sub>;
}

/** 居中的展示公式块 */
export function Formula({ children, caption }: { children: ReactNode; caption?: string }) {
  return (
    <div className="my-6 text-center">
      <div className="inline-block rounded-xl border border-white/10 bg-white/[0.03] px-8 py-5 text-xl md:text-2xl">
        <span className="font-serif italic tracking-wide text-amber-100/95">{children}</span>
      </div>
      {caption && <p className="mt-3 text-sm text-white/40">{caption}</p>}
    </div>
  );
}
