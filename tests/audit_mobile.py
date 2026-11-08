# -*- coding: utf-8 -*-
"""手机端专项审计：触摸目标 / 字号 / 三视图 / 横屏 / 320px 小屏。

只量不修，把问题摆出来。

触摸目标这里量的是「有效点击区」而不是盒子尺寸：★ 收藏、例句里的小喇叭、
历史记录里的 × 都是故意保持小盒子、用 ::after 向外扩点击区的，
只量 getBoundingClientRect 会一直报它们不合格。所以按 44x44 的目标区
取五个点（四角 + 中心）打 elementFromPoint，五个点都命中才算合格。
"""
import json, os, sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Browser, num

HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "output", "index.html")
URL = "file:///" + HTML.replace("\\", "/").replace(" ", "%20")

# 有效点击区探测：返回命中点数（0~5）
HIT = """(function(){
  window.__eff = function(e){
    var r = e.getBoundingClientRect();
    if(r.width===0 || r.height===0) return -1;
    var vw = innerWidth, vh = innerHeight;
    // 落在横向滚动区右边的元素其实看不见，elementFromPoint 也拿不到，跳过
    if(r.left < 0 || r.right > vw || r.top < 0 || r.bottom > vh) return -1;
    // 被横滑容器裁掉一半的元素同理：裁掉那部分本来就点不到，不是元素的锅
    var p = e.parentElement;
    while(p && p !== document.body){
      if(/auto|scroll|hidden/.test(getComputedStyle(p).overflowX)){
        var pr = p.getBoundingClientRect();
        if(r.right > pr.right + 1 || r.left < pr.left - 1) return -1;
        break;
      }
      p = p.parentElement;
    }
    var cx = r.left + r.width/2, cy = r.top + r.height/2;
    var w = Math.max(r.width, 44), h = Math.max(r.height, 44);
    var L = cx - w/2, T = cy - h/2, ok = 0;
    /* 取中心 + 四条边的中点，不取四角：筛选片是胶囊形（border-radius:999px）、
       喇叭是圆角矩形，圆角外的那一小块本来就不属于元素，打角上必然落空，
       那是误报，不是触控目标不合格 */
    [[cx,cy],[cx,T+3],[cx,T+h-3],[L+3,cy],[L+w-3,cy]].forEach(function(p){
      var el = document.elementFromPoint(p[0], p[1]);
      if(el && (el === e || e.contains(el))) ok++;
    });
    return ok;
  };
})()"""

b = Browser(9340)
try:
    b.open(URL, width=390, height=780,
           pre="try{localStorage.clear()}catch(e){}")
    b.send("Emulation.setDeviceMetricsOverride",
           {"width": 390, "height": 780, "deviceScaleFactor": 2, "mobile": True})
    b.ev("render()")

    print("=== 1. 有效点击区不足 44x44 的可点元素（首屏可见的） ===")
    b.ev(HIT)
    r = b.ev("""(function(){
      var out = [];
      document.querySelectorAll('button,.chip,.seg-b,select,.mini,.spk,.star,.qopt,label.eye,.hx')
        .forEach(function(e){
        var cs = getComputedStyle(e);
        if(cs.display === 'none' || cs.visibility === 'hidden') return;
        var ok = window.__eff(e);
        if(ok === -1 || ok === 5) return;
        var b = e.getBoundingClientRect();
        out.push({t:(e.textContent||'').trim().slice(0,14)||e.className.slice(0,18),
                  w:Math.round(b.width), h:Math.round(b.height),
                  c:(e.className||'').toString().slice(0,22), hit:ok});
      });
      return out;
    })()""")
    for x in (r or []):
        print("   %-16s 盒子 %2dx%-3d 命中 %d/5  .%s" % (x['t'], x['w'], x['h'], x['hit'], x['c']))
    print("   合计:", len(r or []), "（0 表示全部达标）")

    print("\n=== 2. 正文字号 < 12px 的元素 ===")
    r2 = b.ev("""(function(){
      var out={};
      document.querySelectorAll('#list *, .chipline *, .bar *, .mbar *, #stats *, #readPanel *, #quizPanel *')
        .forEach(function(e){
        if(!e.textContent.trim()||e.children.length) return;
        var fs=parseFloat(getComputedStyle(e).fontSize);
        if(fs<12){ var k=fs+'px'; out[k]=out[k]||[]; if(out[k].length<4) out[k].push((e.textContent||'').trim().slice(0,16)); }
      });
      return out;
    })()""")
    print("  ", json.dumps(r2, ensure_ascii=False))

    print("\n=== 3. 三视图在 390px 的横向溢出 ===")
    for v in ['card', 'read', 'quiz']:
        b.ev("document.querySelector('#viewSeg .seg-b[data-view=%s]').click()" % v)
        sw = int(num(b.ev("document.documentElement.scrollWidth"), 0))
        ow = b.ev("""(function(){var o=[];document.querySelectorAll('body *').forEach(function(e){
            var r=e.getBoundingClientRect();
            if(r.right>391.5&&r.width>0&&getComputedStyle(e).position!=='fixed'){
              var p=e.parentElement,sc=false;
              while(p&&p!==document.body){if(/auto|scroll/.test(getComputedStyle(p).overflowX)){sc=true;break;}p=p.parentElement;}
              if(!sc) o.push((e.tagName+'.'+e.className).slice(0,30)+' right='+Math.round(r.right));}});
            return o.slice(0,5);})()""")
        print("   %-5s scrollWidth=%d  真正溢出: %s" % (v, sw, ow or '无（其余都在横滑行里）'))

    print("\n=== 4. 做题视图选项按钮尺寸 ===")
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=quiz]').click()")
    r4 = b.ev("""(function(){return [...document.querySelectorAll('#qOpts .qopt')].map(function(e){
        var b=e.getBoundingClientRect();return Math.round(b.width)+'x'+Math.round(b.height);});})()""")
    print("  ", r4)

    print("\n=== 5. 底部操作条（词卡视图） ===")
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=card]').click(); render();")
    b.ev(HIT)
    r5 = b.ev("""(function(){var m=document.querySelector('.mbar');
        if(!m) return 'no-mbar';
        var b=m.getBoundingClientRect();var cs=getComputedStyle(m);
        return {h:Math.round(b.height),disp:cs.display,pos:cs.position,
                btns:[...m.querySelectorAll('button')].filter(function(e){return getComputedStyle(e).display!=='none';})
                  .map(function(e){var r=e.getBoundingClientRect();
                    return (e.textContent.trim().slice(0,6))+':'+Math.round(r.width)+'x'+Math.round(r.height)
                      +' 命中'+window.__eff(e)+'/5';})};})()""")
    print("  ", json.dumps(r5, ensure_ascii=False))

    print("\n=== 6. 横屏 844x390 ===")
    b.send("Emulation.setDeviceMetricsOverride",
           {"width": 844, "height": 390, "deviceScaleFactor": 2, "mobile": True})
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=card]').click(); render();")
    print("   scrollWidth=", num(b.ev("document.documentElement.scrollWidth"), 0),
          " 首卡高度=", num(b.ev("(document.querySelector('#list .card')||{getBoundingClientRect:function(){return{height:0}}}).getBoundingClientRect().height"), 0))

    print("\n=== 7. 小屏 ===")
    for w in (320, 360, 414):
        b.send("Emulation.setDeviceMetricsOverride",
               {"width": w, "height": 700, "deviceScaleFactor": 2, "mobile": True})
        b.ev("render(); window.scrollTo(0,0);")
        print("   %dpx: scrollWidth=%d (应 <= %d)  mbar高=%s  报错=%s"
              % (w, int(num(b.ev("document.documentElement.scrollWidth"), 0)), w + 1,
                 num(b.ev("(document.querySelector('.mbar')||{getBoundingClientRect:function(){return{height:0}}}).getBoundingClientRect().height"), 0),
                 b.ev("window.__errs") or []))
finally:
    b.close()
