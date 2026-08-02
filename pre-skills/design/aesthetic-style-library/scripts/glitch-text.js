/**
 * 工业科技风 · RGB 色差故障文字
 * 源码: kimi-agent-website/src/components/industrial/GlitchText.tsx
 *
 * 用法:
 *   <div class="glitch-text" data-text="故障文字">故障文字</div>
 *   // 或 JS:
 *   const cleanup = createGlitchEffect(el, { auto: true, hover: true });
 */
export function createGlitchEffect(element, opts = {}) {
  const { auto = true, hover = true, autoDelay = 1200, interval = 4000, duration = 200 } = opts;
  if (!element) return () => {};

  let timer = null;
  let loop = null;

  function burst() {
    element.style.textShadow = '3px 0 #FF2E88, -3px 0 #00E5FF';
    element.style.transform = 'translateX(1px) skewX(-2deg)';
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      element.style.textShadow = '';
      element.style.transform = '';
    }, duration);
  }

  if (auto) {
    const first = setTimeout(() => {
      burst();
      loop = setInterval(burst, interval);
    }, autoDelay);
    // 保存引用以便清理
    element._glitchFirst = first;
    element._glitchLoop = loop;
  }

  if (hover) {
    element.addEventListener('mouseenter', burst);
  }

  return function cleanup() {
    if (element._glitchFirst) clearTimeout(element._glitchFirst);
    if (element._glitchLoop) clearInterval(element._glitchLoop);
    element.removeEventListener('mouseenter', burst);
    if (timer) clearTimeout(timer);
    element.style.textShadow = '';
    element.style.transform = '';
  };
}

/* CSS 备用方案: hover 触发故障 */
.glitch-text {
  position: relative;
  display: inline-block;
  transition: text-shadow 0.2s, transform 0.2s;
}
.glitch-text:hover {
  text-shadow: 3px 0 #FF2E88, -3px 0 #00E5FF;
  transform: translateX(1px) skewX(-2deg);
}
