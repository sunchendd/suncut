// jobs.js —— 任务中心:全局任务表 + 实时日志抽屉
import { api, fmtDur } from '../api.js';
import * as bus from '../bus.js';
import { el, clear, statusChip, logBox, toast } from '../ui.js';

export default async function render(root) {
  let jobs = [];
  let openId = null;
  try { jobs = (await api.get('/api/jobs')).jobs; } catch { }

  const tblBody = el('tbody', {});
  const drawer = el('div', {});

  function row(j) {
    const acts = [];
    if (j.status === 'awaiting') {
      acts.push(el('button', { class: 'btn primary sm', onclick: async () => {
        try { await api.post(`/api/jobs/${j.id}/resume`); } catch (e) { toast(e.message, 'bad'); } } }, '放行'));
    }
    if (['queued', 'running', 'awaiting'].includes(j.status) && j.pausable) {
      acts.push(el('button', { class: 'btn danger sm', onclick: async () => {
        try { await api.post(`/api/jobs/${j.id}/cancel`); } catch (e) { toast(e.message, 'bad', 6000); } } }, '取消'));
    }
    return el('tr', { style: openId === j.id ? { background: 'rgba(232,163,61,.06)' } : {}, onclick: () => { openId = j.id; paintDrawer(j.id); paint(); } },
      el('td', {}, statusChip(j.status)),
      el('td', {}, el('b', {}, j.title)),
      el('td', {}, j.project || '-'),
      el('td', { class: 'mono small' }, j.id),
      el('td', {}, fmtDur(j.duration)),
      el('td', { class: 'small dim' }, new Date(j.created_at * 1000).toLocaleString()),
      el('td', {}, ...acts));
  }

  function paint() {
    clear(tblBody);
    if (!jobs.length) tblBody.append(el('tr', {}, el('td', { colspan: '7', class: 'empty' }, '暂无任务')));
    else jobs.forEach(j => tblBody.append(row(j)));
  }
  paint();

  async function paintDrawer(jid) {
    clear(drawer);
    try {
      const j = await api.get(`/api/jobs/${jid}`);
      drawer.append(el('div', { class: 'card accent' },
        el('div', { class: 'spread' },
          el('div', { class: 'row' }, statusChip(j.status), el('b', {}, j.title),
            j.error ? el('span', { class: 'chip bad' }, j.error.slice(0, 80)) : null),
          el('button', { class: 'btn ghost sm', onclick: () => paintDrawer(jid) }, '↻ 刷新')),
        j.meta?.note ? el('div', { class: 'small', style: { margin: '4px 0', color: 'var(--warn)' } }, j.meta.note) : null,
        logBox(j.log.length ? j.log : '(无输出)', '380px')));
    } catch (e) { drawer.append(el('div', { class: 'empty' }, e.message)); }
  }

  root.append(
    el('h1', {}, '任务中心'),
    el('p', { class: 'page-sub' }, '同一项目同时只跑一个任务(state 无锁防覆盖);GPU 类任务全局串行(infer 与 ComfyUI 互斥占卡)。'),
    el('div', { class: 'card', style: { padding: '6px 10px' } },
      el('div', { class: 'scroll-x' },
        el('table', { class: 'tbl' },
          el('thead', {}, el('tr', {},
            el('th', {}, '状态'), el('th', {}, '任务'), el('th', {}, '项目'), el('th', {}, 'ID'),
            el('th', {}, '耗时'), el('th', {}, '提交于'), el('th', {}, '操作'))),
          tblBody))),
    drawer);

  const offLog = bus.on('log', (m) => { if (m.id === openId) paintDrawer(openId); });
  const offJob = bus.on('job', async (j) => {
    const i = jobs.findIndex(x => x.id === j.id);
    if (i >= 0) jobs[i] = j; else jobs.unshift(j);
    paint();
    if (openId === j.id) paintDrawer(j.id);
  });
  return { dispose: () => { offLog(); offJob(); } };
}
