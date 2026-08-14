import { type ReactNode } from 'react';
import { useInView } from '@/hooks/use-in-view';

interface RevealProps {
  children: ReactNode;
  delay?: number; // ms
  className?: string;
}

/** 滚动进入视口时的淡入上移动效（交错延迟） */
export default function Reveal({ children, delay = 0, className = '' }: RevealProps) {
  const { ref, inView } = useInView<HTMLDivElement>(0.15);
  return (
    <div
      ref={ref}
      className={`transition-all duration-700 ease-out ${className}`}
      style={{
        opacity: inView ? 1 : 0,
        transform: inView ? 'translateY(0)' : 'translateY(24px)',
        transitionDelay: `${delay}ms`,
      }}
    >
      {children}
    </div>
  );
}
