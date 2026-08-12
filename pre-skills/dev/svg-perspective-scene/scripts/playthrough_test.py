#!/usr/bin/env python3
"""自动点击回归: 注入 click-driver 生成带 driver 的 HTML 副本, 交由浏览器工具集打开与诊断。

用法:
  python playthrough_test.py <html绝对路径> <steps片段文件> <输出html路径> [--report-at 15000]

  生成 <输出html路径>: 在原 HTML </body> 前注入 click-driver。
  随后由 agent 用浏览器工具集打开该文件, 等到 report-at 时刻, 用
  browser_query(selector="title") 读取 document.title 作为诊断回传。

  典型 agent 流程:
    1. python playthrough_test.py input.html steps.js ws:output/test_injected.html --report-at 15000
    2. browser_open_tab(url="file:///<输出html绝对路径>")
    3. browser_list_tabs → 取下标 idx
    4. browser_wait(tab=idx, timeout_ms=<report-at + 余量>)
    5. browser_query(tab=idx, selector="title") → 读 title 文本

<steps片段文件> 是 JS 代码片段, 用 step(毫秒, ()=>C('选择器')) 编排点击时刻表,
可用工具:
  C(sel)   - 对选择器派生真实 click (bubbles, 触发热区/按钮)
  step(t,f)- setTimeout 包装
  R(sel,attr) - 读取元素属性/样式, 用于末尾诊断
时刻表须晚于被测页面自身的 setTimeout 剧情串联, 并预留余量。

脚本自动附加: 全局 error 收集 + 末尾把全部结果写入 document.title。

示例 steps 片段:
  step(500,  ()=>C('[data-key=rug]'));
  step(1500, ()=>C('#floorKey'));
  step(2500, ()=>{ for(let i=0;i<6;i++) C('#cHp'); });
  // 末尾(必须): 汇报
  report(()=>[
    'doorTf=' + R('#doorPanel','style').transform,
    'err=' + (window._err||'none')
  ].join(' | '));
"""
import argparse

PRELUDE = """
<script>
(function(){
  const C = (sel)=>{ const el = document.querySelector(sel);
    if(el){ el.dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:400,clientY:300})); return true; }
    window._miss = (window._miss||'') + ' MISS:' + sel; return false; };
  const R = (sel,prop)=>{ const el = document.querySelector(sel);
    if(!el) return '<absent>'; return prop.split('.').reduce((o,k)=>o&&o[k], el); };
  const step = (t,fn)=>setTimeout(fn, t);
  window.addEventListener('error', e=>{ window._err = (window._err||'') + ' [' + e.message + ':' + e.lineno + ']'; });
  const report = (fn)=>setTimeout(()=>{ document.title = fn() + (window._miss||''); }, __REPORT_AT__);
"""

POSTLUDE = """
})();
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('html', help='原 HTML 绝对路径')
    ap.add_argument('steps', help='steps 片段文件路径')
    ap.add_argument('out', help='注入 driver 后的输出 HTML 路径')
    ap.add_argument('--report-at', default=15000, type=int,
                    help='诊断写入 title 的时刻(ms), 默认 15000')
    a = ap.parse_args()

    src = open(a.html, encoding='utf-8').read()
    steps = open(a.steps, encoding='utf-8').read()
    driver = PRELUDE.replace('__REPORT_AT__', str(a.report_at)) + steps + POSTLUDE

    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(src.replace('</body>', driver + '\n</body>'))
    print('injected:', a.out)
    print('report_at_ms:', a.report_at)
    wait_ms = a.report_at + 2000
    print('next: browser_open_tab(file:///%s) → browser_wait(timeout_ms=%d) → browser_query(selector="title")'
          % (a.out, wait_ms))


if __name__ == '__main__':
    main()
