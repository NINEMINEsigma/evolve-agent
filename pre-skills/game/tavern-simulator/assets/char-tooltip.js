/* =============================================
   char-tooltip.js — 正文角色 tooltip 交互（通用版）
   使用方式：
   1. 在页面末尾内嵌角色数据（JS 对象，不是 JSON 元素）：
      <script>window.__TT_DATA__ = { "角色key": {...} };</script>
   2. 本脚本必须放在 __TT_DATA__ 之后
   3. 正文用 <span class="ch" data-ch="角色key">名字/代词</span> 包裹
   数据结构：
   {
     "key": {
       name: "显示名",
       emoji: "👩",
       title: "身份行（可选）",
       fields: [ ["标签","值"], ... ],   // 任意字段，Agent 每回合定制
       affection: 92                     // 可选，0-100 渲染好感度条
     }
   }
   实现要点：IIFE + document.currentScript.parentElement 按消息容器隔离绑定，
   tooltip 浮层全局唯一（#tt-tip），多消息并存不冲突。
   ============================================= */
(function(){
  var root = document.currentScript ? document.currentScript.parentElement : document.body;
  var DATA = window.__TT_DATA__ || {};

  var tip = document.getElementById('tt-tip');
  if(!tip){ tip = document.createElement('div'); tip.id = 'tt-tip'; document.body.appendChild(tip); }
  var open = null;

  function hide(){
    tip.style.display = 'none';
    open = null;
  }

  function show(key, anchor){
    var c = DATA[key];
    if(!c) return;
    var h = '';
    h += '<div class="tt-cn2">' + (c.emoji || '📖') + ' ' + c.name + '</div>';
    if(c.title) h += '<div class="tt-ct2">' + c.title + '</div>';
    if(c.fields && c.fields.length){
      for(var i = 0; i < c.fields.length; i++){
        var f = c.fields[i];
        if(!f || !f[0] || !f[1]) continue;
        h += '<div class="tt-cr2"><span class="tt-cl2">' + f[0] + '</span><span class="tt-cv2">' + f[1] + '</span></div>';
      }
    }
    if(typeof c.affection === 'number'){
      var aff = Math.max(0, Math.min(100, c.affection));
      h += '<div class="tt-cp2"><span class="tt-cl2" style="min-width:56px;">❤️ 好感</span><span class="tt-cb2"><div class="tt-cf2" style="width:' + aff + '%"></div></span><span class="tt-sn2">' + aff + '%</span></div>';
    }
    tip.innerHTML = h;
    tip.style.display = 'block';

    var r = anchor.getBoundingClientRect();
    var th = tip.offsetHeight;
    var x = Math.min(r.left, window.innerWidth - 238 - 8); if(x < 8) x = 8;
    var y = r.bottom + 6; if(y + th > window.innerHeight - 8) y = Math.max(8, r.top - th - 6);
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
    open = key;
  }

  root.addEventListener('click', function(e){
    var el = e.target.closest ? e.target.closest('.ch') : null;
    if(!el || !root.contains(el)) return;
    e.stopPropagation();
    var key = el.getAttribute('data-ch');
    if(open === key){ hide(); return; }
    show(key, el);
  });

  document.addEventListener('click', function(e){
    if(!e.target.closest || !e.target.closest('.ch')) hide();
  });

  window.addEventListener('scroll', hide, true);
  window.chTipHide = hide;
})();
