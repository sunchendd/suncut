// main.js —— 入口:hash 路由 + WS 全局任务追踪 + 侧栏项目列表
import { api } from './api.js';
import * as bus from './bus.js';
import { el, clear, toast } from './ui.js';
import dashboard from './views/dashboard.js';
import project from './views/project.js';
import jobsView from './views/jobs.js';
import poolView from './views/pool.js';
import systemView from './views/system.js';

const view = document.getElementById('view');
let current = null;                    // { dispose(), onJob(job), refresh() }

const ROUTES = [
  [/^#\/dashboard$/, dashboard],
  [/^#\/project\/(.+)$/, project],
  [/^#\/jobs$/, jobsView],
  [/^#\/pool$/, poolView],
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
  highlightNav(hash);
}

function highlightNav(hash) {
  const key = (hash.match(/^#\/(\w+)/) || [])[1] || 'dashboard';
  document.querySelectorAll('#sidenav a[data-nav]').forEach(a =>
    a.classList.toggle('active', a.dataset.nav === key));
  document.querySelectorAll('#nav-projects a').forEach(a =>
    a.classList.toggle('active', hash === `#/project/${a.dataset.name}`));
}

// ---------------- 侧栏项目列表 ----------------
async function refreshSidenav() {
  try { store.overview = await api.get('/api/overview'); } catch { return; }
  const box = document.getElementById('nav-projects');
  clear(box);
  box.append(el('div', { class: 'nav-group-title' }, '项目'));
  for (const p of store.overview.projects.slice(0, 12)) {
    const a = el('a', { href: `#/project/${p.name}`, dataset: { name: p.name } },
      `${p.busy ? '⏳' : (p.stages.review ? '🎬' : '📝')} ${p.title || p.name}`);
    box.append(a);
  }
  highlightNav(location.hash);
}

// ---------------- 全局任务事件 ----------------
bus.on('resync', () => {          // WS 断线重连后:全量重拉,防止漏事件
  refreshSidenav();
  if (current?.refresh) current.refresh();
});
bus.on('job', (m) => {
  const j = m.job;
  const prev = store.jobs.get(j.id);
  store.jobs.set(j.id, j);
  if (current?.onJob) current.onJob(j);
  if (prev && prev.status !== j.status) {
    if (j.status === 'failed') toast(`❌ 任务失败:${j.title} —— ${j.error || ''}`, 'bad', 8000);
    else if (j.status === 'awaiting') toast(`⏸ ${j.title}:${j.meta?.note || '等待人工放行'}`, 'warn', 6000);
    else if (j.status === 'done') toast(`✅ ${j.title} 完成`, 'ok');
    else if (j.status === 'cancelled') toast(`任务已取消:${j.title}`, 'info');
  }
  if (['done', 'failed', 'cancelled'].includes(j.status)) {
    refreshSidenav();
    if (current?.refresh) current.refresh();
  }
});
bus.onStatus((on) => {
  document.getElementById('ws-dot').className = `ws-dot ${on ? 'on' : 'off'}`;
  document.getElementById('ws-dot').title = on ? '实时通道已连接' : '实时通道断开,重连中…';
});

bus.start();
refreshSidenav();
window.addEventListener('hashchange', route);
route();
