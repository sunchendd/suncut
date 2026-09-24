// logs.js —— 项目内「任务与日志」面板:本项目任务历史 + 展开看日志
import { api, fmtDur } from '../api.js';
import * as bus from '../bus.js';
import { el, clear, statusChip, logBox } from '../ui.js';

export default function render(ctx) {
  const { name } = ctx;
  const list = el('div', {});
  const box = el('div', {},
    el('h2', {}, '任务与日志'),
    el('p', { class: 'page-sub' }, '本项目的任务历史(服务重启后清空;产物与断点状态在磁盘,不受影响)。'),
    list);

  async function fillBody(body, jid) {
    clear(body);
    try {
      const j = await api.get(`/api/jobs/${jid}`);
      body.append(logBox(j.log.length ? j.log : '(无输出)', '260px'));
      if (j.error) body.append(el('div', { class: 'small', style: { color: 'var(--bad)', whiteSpace: 'pre-wrap' } }, j.error));
      if (j.meta?.trace) body.append(el('details', {}, el('summary', { class: 'small dim' }, '堆栈'), el('pre', { class: 'box small' }, j.meta.trace)));
    } catch (e) { body.append(el('div', { class: 'small faint' }, e.message)); }
  }

  async function paint() {
    let jobs = [];
    try { jobs = (await api.get(`/api/jobs?project=${encodeURIComponent(name)}`)).jobs; } catch { }
    clear(list);
    if (!jobs.length) { list.append(el('div', { class: 'card empty' }, '暂无任务')); return; }
    for (const j of jobs) {
      const body = el('div', {});
      list.append(el('details', { class: 'card', style: { padding: '8px 14px' },
        ontoggle: (e) => { if (e.target.open) fillBody(body, j.id); } },
        el('summary', { class: 'row' }, statusChip(j.status), el('b', {}, j.title),
          el('span', { class: 'small dim' }, `${new Date(j.created_at * 1000).toLocaleString()} · ${fmtDur(j.duration)}`)),
        body));
    }
  }
  paint();

  const off = bus.on('job', (j) => {
    if (j.project === name && ['done', 'failed', 'cancelled'].includes(j.status)) paint();
  });
  box._dispose = off;
  return box;
}
