/* 由 core/exporters.py 的 build_pwa() 生成，不要手改。
   策略：
   · 导航请求网络优先 —— 重新构建后打开就是新版，断网才用缓存；
   · 其它同源 GET 缓存优先 —— 单文件页面本来就没有外部依赖。 */
const CACHE = 'cet4-202611082123';
const CORE = ['./index.html', './manifest.webmanifest', './icon.svg'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(CORE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).then(res => {
      const cp = res.clone();
      caches.open(CACHE).then(c => c.put(req, cp));
      return res;
    }).catch(() => caches.match('./index.html')));
    return;
  }
  e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => {
    const cp = res.clone();
    caches.open(CACHE).then(c => c.put(req, cp));
    return res;
  })));
});
