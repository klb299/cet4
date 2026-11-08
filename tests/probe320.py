# -*- coding: utf-8 -*-
"""320px 溢出定位 v2：不做祖先过滤，按 right 排序，最外面那个就是真凶。"""
import os, sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Browser, num

URL = "file:///" + os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "output", "index.html").replace("\\", "/").replace(" ", "%20")

b = Browser(9341)
try:
    b.open(URL, width=320, height=600, pre="try{localStorage.clear()}catch(e){}")
    b.send("Emulation.setDeviceMetricsOverride",
           {"width": 320, "height": 640, "deviceScaleFactor": 2, "mobile": True})
    b.ev("render()")
    print("scrollWidth =", int(num(b.ev("document.documentElement.scrollWidth"), 0)))
    print("body.scrollWidth =", int(num(b.ev("document.body.scrollWidth"), 0)))
    # 逐个藏掉 body 的直接子节点，看谁一藏 scrollWidth 就降下来
    print("\n--- 逐个隐藏 body 子节点 ---")
    r = b.ev("""(function(){
      var out=[], kids=[...document.body.children], base=document.documentElement.scrollWidth;
      out.push({w:base, who:'(基线)'});
      kids.forEach(function(k){
        var old=k.style.display; k.style.display='none';
        out.push({w:document.documentElement.scrollWidth, who:k.tagName+'.'+(k.className||'').slice(0,20)+'#'+(k.id||'')});
        k.style.display=old;
      });
      return out;
    })()""")
    for x in (r or []):
        print("   scrollWidth=%-5d 隐藏 %s" % (x['w'], x['who']))

    print("\n--- 320px 下所有 right>321 的元素（按 deep 排序，取最浅的 20 个）---")
    r2 = b.ev("""(function(){
      var out=[];
      document.querySelectorAll('body *').forEach(function(e){
        var cs=getComputedStyle(e);
        if(cs.display==='none'||cs.visibility==='hidden') return;
        var rc=e.getBoundingClientRect();
        if(rc.width===0||rc.right<=321) return;
        var d=0,p=e; while(p){d++;p=p.parentElement;}
        out.push({d:d, t:e.tagName+'.'+(e.className||'').toString().slice(0,22),
                  w:Math.round(rc.width), r:Math.round(rc.right),
                  sw:e.scrollWidth, cw:e.clientWidth,
                  txt:(e.textContent||'').trim().slice(0,20)});
      });
      out.sort(function(a,b){return a.d-b.d || b.r-a.r;});
      return out.slice(0,20);
    })()""")
    for x in (r2 or []):
        print("   深%-2d %-30s w=%-4d right=%-5d scrollW=%-5d clientW=%-4d %s"
              % (x['d'], x['t'], x['w'], x['r'], x['sw'], x['cw'], x['txt']))
finally:
    b.close()
