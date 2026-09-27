// main.js —— 入口:hash 路由 + WS 全局任务追踪 + 顶栏(跑马灯/外观) + 分组侧栏
import { api } from './api.js';
import * as bus from './bus.js';
import { el, clear, toast } from './ui.js';
import { prefs } from './prefs.js';
import dashboard, { newProjectModal } from './views/dashboard.js';
import project from './views/project.js';
import jobsView from './views/jobs.js';
import poolView from './views/pool.js';
import assetsView from './views/assets.js';
import systemView from './views/system.js';

const view = document.getElementById('view');
let current = null;                    // { dispose(), onJob(job), refresh() }

const ROUTES = [
  [/^#\/dashboard$/, dashboard],
  [/^#\/project\/(.+)$/, project],
  [/^#\/jobs$/, jobsView],
  [/^#\/pool$/, poolView],
  [/^#\/assets$/, assetsView],
  [/^#\/system$/, systemView],
];

export const store = {
  jobs: new Map(),                     // id -> dto(含终态前状态)
  overview: null,
};

async function route() {
  const hash = location.hash || '#/dashboard';
  if (current?.dispose) current.dispose();
  clear(view);
  current = null;
  for (const [re, fn] of ROUTES) {
    const m = hash.match(re);
    if (m) {
      current = (await fn(view, ...m.slice(1))) || {};
      break;
    }
  }
  if (!current) view.append(el('div', { class: 'empty' }, '页面不存在:', hash));
  // 视图进场过渡(重触发动画)
  view.classList.remove('view-enter');
  void view.offsetWidth;
  view.classList.add('view-enter');
  highlightNav(hash);
}

function highlightNav(hash) {
  const key = (hash.match(/^#\/(\w+)/) || [])[1] || 'dashboard';
  document.querySelectorAll('#sidenav a[data-nav]').forEach(a =>
    a.classList.toggle('active', a.dataset.nav === key));
  document.querySelectorAll('#nav-projects a').forEach(a =>
    a.classList.toggle('active', hash === `#/project/${a.dataset.name}`));
}

// ---------------- 侧栏项目列表(合帧重绘;不用 rAF —— 后台标签页/不可见面板会挂起导致侧栏空白) ----------------
let sidePending = false;
function scheduleSidenav() {
  if (sidePending) return;
  sidePending = true;
  setTimeout(() => { sidePending = false; paintSidenav(); }, 0);
}

function paintSidenav() {
  const box = document.getElementById('nav-projects');
  if (!box) return;
  clear(box);
  const ps = store.overview?.projects || [];
  if (!ps.length) box.append(el('div', { class: 'nav-group-label', style: { opacity: '.8' } }, '还没有项目'));
  for (const p of ps) {
    const badge = p.busy
      ? el('span', { class: 'nav-badge run' }, '运行')
      : (p.stages?.review
        ? el('span', { class: 'nav-badge done' }, '成片')
        : (p.stages?.cast ? el('span', { class: 'nav-badge' }, '制作') : null));
    const dot = el('span', {
      class: 'status-dot',
      style: { margin: '0', background: p.busy ? 'var(--info)' : p.stages?.review ? 'var(--ok)' : 'var(--fg-faint)', animation: p.busy ? 'breath 1.8s infinite' : 'none' },
    });
    box.append(el('a', { href: `#/project/${p.name}`, dataset: { name: p.name }, title: p.title || p.name },
      dot, el('span', { class: 'txt' }, p.title || p.name), badge));
  }
  highlightNav(location.hash);
}

async function refreshSidenav() {
  try { store.overview = await api.get('/api/overview'); } catch { return; }
  scheduleSidenav();
}

// ---------------- 顶栏:任务跑马灯 ----------------
function paintTicker() {
  const box = document.getElementById('ticker');
  if (!box) return;
  clear(box);
  const live = [...store.jobs.values()].find(j => ['queued', 'running', 'awaiting'].includes(j.status));
  if (live) {
    box.append(el('a', { class: 'ticker-pill', href: '#/jobs',
      title: live.status === 'awaiting' ? '等待人工放行 —— 点击去处理' : '运行中 —— 点击查看任务中心' },
      el('span', { class: 'breath', style: { background: live.status === 'awaiting' ? 'var(--warn)' : 'var(--info)' } }),
      el('span', { class: 't-title' }, `${live.status === 'awaiting' ? '⏸ 待放行' : '⚙ 运行中'} · ${live.title}`)));
  } else {
    box.append(el('span', { class: 'ticker-pill idle', title: '所有产线空闲' },
      el('span', { class: 'breath', style: { background: 'var(--ok)' } }),
      el('span', { class: 't-title' }, '产线空闲 · 一句话梗概即可开拍')));
  }
}

// ---------------- 顶栏:外观与设置 ----------------
const SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>';
const MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';

function paintThemeBtn() {
  const btn = document.getElementById('theme-btn');
  if (!btn) return;
  btn.innerHTML = prefs.get().theme === 'dark' ? SUN : MOON;
  btn.title = prefs.get().theme === 'dark' ? '切换到蓝白主题' : '切换到暗色主题';
}

function buildSettingsPop() {
  const wrap = document.querySelector('.pop-wrap');
  if (!wrap) return;
  const btn = document.getElementById('settings-btn');   // 先持引用:clear 后再 getElementById 会得到 null(节点已脱离文档树)
  clear(wrap);
  wrap.append(btn);
  const p = prefs.get();

  const seg = el('div', { class: 'seg' },
    el('button', { class: p.theme === 'light' ? 'on' : '', onclick: () => { prefs.set('theme', 'light'); paintThemeBtn(); closePop(); } }, '蓝白'),
    el('button', { class: p.theme === 'dark' ? 'on' : '', onclick: () => { prefs.set('theme', 'dark'); paintThemeBtn(); closePop(); } }, '暗色'));
  const motionSw = el('button', { class: `switch ${p.motion === 'on' ? 'on' : ''}`, onclick: () => {
    prefs.set('motion', prefs.get().motion === 'on' ? 'off' : 'on');
    motionSw.classList.toggle('on', prefs.get().motion === 'on');
  } });
  const sideSw = el('button', { class: `switch ${p.side === 'collapsed' ? 'on' : ''}`, onclick: () => {
    prefs.set('side', prefs.get().side === 'collapsed' ? 'open' : 'collapsed');
    sideSw.classList.toggle('on', prefs.get().side === 'collapsed');
    syncSideToggle();
  } });

  const pop = el('div', { class: 'popover' },
    el('div', { class: 'pop-title' }, '外观'),
    el('div', { class: 'pop-item' }, el('div', { class: 'lbl' }, '主题配色', el('span', { class: 'hint' }, '蓝白为默认')), seg),
    el('div', { class: 'pop-item' }, el('div', { class: 'lbl' }, '界面动效', el('span', { class: 'hint' }, '过渡/悬浮/呼吸灯')), motionSw),
    el('div', { class: 'pop-item' }, el('div', { class: 'lbl' }, '折叠侧栏', el('span', { class: 'hint' }, '只留图标,腾出画布')), sideSw));
  wrap.append(pop);

  const onDoc = (e) => { if (!wrap.contains(e.target)) closePop(); };
  const closePop = () => { clear(wrap); wrap.append(btn); document.removeEventListener('click', onDoc); };
  setTimeout(() => document.addEventListener('click', onDoc), 0);
}

function syncSideToggle() {
  const side = document.getElementById('sidenav');
  const txt = document.querySelector('#side-toggle .txt');
  if (side && txt) txt.textContent = side.classList.contains('collapsed') ? '' : '收起侧栏';
}

// ---------------- 全局任务事件 ----------------
let refreshTimer = null;
function scheduleRefresh() {           // 终态事件合并一次重拉,避免短时间多次全量刷新
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => {
    refreshSidenav();
    if (current?.refresh) current.refresh();
  }, 400);
}

bus.on('resync', () => {          // WS 断线重连后:全量重拉,防止漏事件
  refreshSidenav();
  if (current?.refresh) current.refresh();
});
bus.on('job', (m) => {
  const j = m.job;
  const prev = store.jobs.get(j.id);
  const terminal = ['done', 'failed', 'cancelled'].includes(j.status);
  if (terminal) store.jobs.delete(j.id);   // 终态不占跑马灯
  else store.jobs.set(j.id, j);
  paintTicker();
  if (current?.onJob) current.onJob(j);
  if (prev && prev.status !== j.status) {
    if (j.status === 'failed') toast(`❌ 任务失败:${j.title} —— ${j.error || ''}`, 'bad', 8000);
    else if (j.status === 'awaiting') toast(`⏸ ${j.title}:${j.meta?.note || '等待人工放行'}`, 'warn', 6000);
    else if (j.status === 'done') toast(`✅ ${j.title} 完成`, 'ok');
    else if (j.status === 'cancelled') toast(`任务已取消:${j.title}`, 'info');
  }
  if (terminal) scheduleRefresh();
});
bus.onStatus((on) => {
  const dot = document.getElementById('ws-dot');
  if (dot) {
    dot.className = `ws-dot ${on ? 'on' : 'off'}`;
    document.getElementById('ws-wrap').title = on ? '实时通道已连接' : '实时通道断开,重连中…';
  }
});

// ---------------- 启动 ----------------
prefs.apply();
paintThemeBtn();
document.getElementById('theme-btn').addEventListener('click', () => {
  prefs.set('theme', prefs.get().theme === 'dark' ? 'light' : 'dark');
  paintThemeBtn();
});
document.getElementById('settings-btn').addEventListener('click', (e) => {
  e.stopPropagation();
  buildSettingsPop();
});
document.getElementById('side-toggle').addEventListener('click', () => {
  const side = document.getElementById('sidenav');
  prefs.set('side', side.classList.contains('collapsed') ? 'open' : 'collapsed');
  syncSideToggle();
});
document.getElementById('new-proj-btn').addEventListener('click', newProjectModal);
document.getElementById('nav-add-proj').addEventListener('click', newProjectModal);
syncSideToggle();

bus.start();
paintTicker();
refreshSidenav();
// WS 只推状态变化,不重播已有任务:启动时拉一次活跃任务,跑马灯才不会假显示"空闲"
api.get('/api/jobs').then(r => {
  for (const j of (r.jobs || [])) {
    if (['queued', 'running', 'awaiting'].includes(j.status)) store.jobs.set(j.id, j);
  }
  paintTicker();
}).catch(() => {});
window.addEventListener('hashchange', route);
route();
