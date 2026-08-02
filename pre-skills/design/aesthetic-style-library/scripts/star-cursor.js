/**
 * 二次元可爱风 · 星星拖尾光标
 * 源码: kimi-agent-website/src/components/kawaii/StarCursor.tsx
 *
 * 用法:
 *   const cleanup = createStarCursor();
 *   // 页面销毁时: cleanup();
 */
export function createStarCursor(opts = {}) {
  const { colors = ['#FF9EC7', '#B8A7F9', '#FFE29A', '#A8E6CF'], maxStars = 24 } = opts;
  if (!window.matchMedia('(pointer: fine)').matches) return () => {};

  const container = document.createElement('div');
  container.style.cssText = 'pointer-events:none;position:fixed;inset:0;z-index:99975;';
  document.body.appendChild(container);

  let stars = [];
  let lastX = -100, lastY = -100;
  let seq = 0;
  let colorIdx = 0;

  function createSparkleSVG(size, color) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', size);
    svg.setAttribute('height', size);
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.style.position = 'absolute';
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('fill', color);
    path.setAttribute('d', 'M12 1.5c1.1 5.4 3.9 8.2 9.3 9.3-5.4 1.1-8.2 3.9-9.3 9.3-1.1-5.4-3.9-8.2-9.3-9.3 5.4-1.1 8.2-3.9 9.3-9.3z');
    svg.appendChild(path);
    return svg;
  }

  function onMove(e) {
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    if (Math.hypot(dx, dy) < 26) return;
    lastX = e.clientX;
    lastY = e.clientY;

    const id = ++seq;
    const color = colors[colorIdx++ % colors.length];
    const size = 9 + Math.random() * 9;

    const star = document.createElement('div');
    star.style.cssText = `position:absolute;left:${e.clientX + (Math.random()*10-5)}px;top:${e.clientY + (Math.random()*10-5)}px;transform:rotate(${Math.random()*90-45}deg);opacity:0.95;transition:all 0.6s ease-out;`;
    star.dataset.id = id;
    const svg = createSparkleSVG(size, color);
    star.appendChild(svg);
    container.appendChild(star);

    stars.push({ id, el: star });

    // 裁剪
    while (stars.length > maxStars) {
      const oldest = stars.shift();
      oldest.el.remove();
    }

    // 渐隐
    requestAnimationFrame(() => {
      star.style.opacity = '0';
      star.style.transform = `rotate(${Math.random()*90-45}deg) translateY(-12px) scale(0)`;
    });

    setTimeout(() => {
      star.remove();
      stars = stars.filter(s => s.id !== id);
    }, 650);
  }

  window.addEventListener('pointermove', onMove, { passive: true });

  return function cleanup() {
    window.removeEventListener('pointermove', onMove);
    container.remove();
  };
}
