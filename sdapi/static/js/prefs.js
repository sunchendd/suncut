// prefs.js —— 外观偏好:主题(蓝白/暗色)/ 动效 / 侧栏折叠,localStorage 持久化
const KEY = 'suncut.prefs';

const DEFAULTS = { theme: 'light', motion: 'on', side: 'open' };

function read() {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') }; }
  catch { return { ...DEFAULTS }; }
}

function write(p) {
  try { localStorage.setItem(KEY, JSON.stringify(p)); } catch { /* 隐身模式等 */ }
}

function apply(p) {
  const root = document.documentElement;
  root.dataset.theme = p.theme === 'dark' ? 'dark' : 'light';
  root.dataset.motion = p.motion === 'off' ? 'off' : 'on';
  const side = document.getElementById('sidenav');
  if (side) side.classList.toggle('collapsed', p.side === 'collapsed');
}

export const prefs = {
  get: read,
  set(key, val) {
    const p = read(); p[key] = val; write(p); apply(p);
  },
  apply: () => apply(read()),
};
