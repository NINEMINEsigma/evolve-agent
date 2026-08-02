/**
 * 工业科技风 · 准星光标
 * 源码: kimi-agent-website/src/components/industrial/CrosshairCursor.tsx
 *
 * 用法:
 *   const cleanup = createCrosshairCursor({ color: '#00E5FF', stiffness: 400, damping: 30 });
 *   // 页面销毁时: cleanup();
 *
 * 需要在页面容器上添加:
 *   @media (pointer: fine) { .skin-industrial, .skin-industrial * { cursor: none !important; } }
 */
export function createCrosshairCursor(opts = {}) {
  const { color = '#00E5FF', stiffness = 400, damping = 30 } = opts;
  if (!window.matchMedia('(pointer: fine)').matches) return () => {};

  // DOM 元素
  const container = document.createElement('div');
  container.style.cssText = 'pointer-events:none;position:fixed;left:0;top:0;z-index:99999;';

  // 垂直线
  const vLine = document.createElement('div');
  vLine.style.cssText = 'position:absolute;left:0;top:0;width:1px;height:24px;transform:translate(-50%,-50%);';
  vLine.style.background = color + 'BF';

  // 水平线
  const hLine = document.createElement('div');
  hLine.style.cssText = 'position:absolute;left:0;top:0;height:1px;width:24px;transform:translate(-50%,-50%);';
  hLine.style.background = color + 'BF';

  // 中心点
  const dot = document.createElement('div');
  dot.style.cssText = 'position:absolute;left:0;top:0;width:3px;height:3px;border-radius:50%;transform:translate(-50%,-50%);';
  dot.style.background = color;

  // 四个寻像器括号
  const brackets = [];
  const bracketPos = [
    { cls: '-left-[18px] -top-[18px]', border: 'border-l border-t' },
    { cls: '-right-[18px] -top-[18px]', border: 'border-r border-t' },
    { cls: '-bottom-[18px] -left-[18px]', border: 'border-b border-l' },
    { cls: '-bottom-[18px] -right-[18px]', border: 'border-b border-r' },
  ];
  for (const bp of bracketPos) {
    const el = document.createElement('div');
    el.style.cssText = `position:absolute;width:10px;height:10px;opacity:0;transition:opacity 0.18s,transform 0.18s;`;
    el.style.borderColor = color;
    // 用 class 来设置边框位置
    if (bp.border.includes('border-l')) el.style.borderLeft = '1px solid ' + color;
    if (bp.border.includes('border-r')) el.style.borderRight = '1px solid ' + color;
    if (bp.border.includes('border-t')) el.style.borderTop = '1px solid ' + color;
    if (bp.border.includes('border-b')) el.style.borderBottom = '1px solid ' + color;
    if (bp.cls.includes('-left-')) el.style.left = '-18px';
    if (bp.cls.includes('-right-')) el.style.right = '-18px';
    if (bp.cls.includes('-top-')) el.style.top = '-18px';
    if (bp.cls.includes('-bottom-')) el.style.bottom = '-18px';
    brackets.push(el);
    container.appendChild(el);
  }

  container.appendChild(vLine);
  container.appendChild(hLine);
  container.appendChild(dot);
  document.body.appendChild(container);

  // 物理状态
  let mx = -100, my = -100;
  let tx = -100, ty = -100;
  let visible = false;
  let hoverEl = false;

  // 弹簧物理 (verlet integration approximation)
  function spring(target, current) {
    const force = (target - current) * (stiffness * 0.001);
    const vel = force / damping;
    return current + vel;
  }

  function animate() {
    mx = spring(tx, mx);
    my = spring(ty, my);
    container.style.transform = `translate(${mx}px, ${my}px)`;
    container.style.opacity = visible ? '1' : '0';
    for (const b of brackets) {
      b.style.opacity = hoverEl ? '1' : '0';
      b.style.transform = hoverEl ? 'scale(1)' : 'scale(1.4)';
    }
    requestAnimationFrame(animate);
  }
  animate();

  function onMove(e) {
    tx = e.clientX;
    ty = e.clientY;
    visible = true;
  }
  function onOver(e) {
    const t = e.target;
    hoverEl = !!t?.closest('a,button,input,textarea,select,label,[role="button"],[role="switch"]');
  }
  function onLeave() { visible = false; }

  window.addEventListener('mousemove', onMove, { passive: true });
  window.addEventListener('mouseover', onOver, { passive: true });
  document.documentElement.addEventListener('mouseleave', onLeave);

  return function cleanup() {
    window.removeEventListener('mousemove', onMove);
    window.removeEventListener('mouseover', onOver);
    document.documentElement.removeEventListener('mouseleave', onLeave);
    container.remove();
  };
}
