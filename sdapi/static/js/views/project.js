// project.js —— 项目工作台:阶段步进器 + 7 个 agent 面板 + 实时任务条
import { api, mediaUrl } from '../api.js';
import * as bus from '../bus.js';
import { el, clear, toast, modal, confirmModal, logBox, statusChip } from '../ui.js';
import casting from '../panels/casting.js';
import materials from '../panels/materials.js';
import screenwriter from '../panels/screenwriter.js';
import storyboard from '../panels/storyboard.js';
import director from '../panels/director.js';
import reviewer from '../panels/reviewer.js';
import producer from '../panels/producer.js';
import logsPanel from '../panels/logs.js';

const TABS = [
  ['cast', 'casting', '① 招聘', casting],
  ['materials', 'materials', '② 物料', materials],
  ['script', 'screenwriter', '③ 编剧', screenwriter],
  ['storyboard', 'storyboard', '④ 分镜', storyboard],
  ['generate', 'director', '⑤ 导演', director],
  ['review', 'reviewer', '⑥ 审片', reviewer],
  ['deliver', 'producer', '⑦ 制片', producer],
  [null, 'logs', '🧾 任务与日志', logsPanel],
];

export default async function render(root, name) {
  let d = null;
  try { d = await api.get(`/api/projects/${name}`); } catch (e) {
    root.append(el('div', { class: 'empty' }, `项目加载失败:${e.message}`)); return;
  }
  if (!d) { root.append(el('div', { class: 'empty' }, '项目不存在')); return; }

  const disposers = [];
  let activeTab = TABS.find(([k]) => k && !d.stages[k])?.[1]
    || (d.busy?.meta?.stage && TABS.find(([k]) => k === d.busy.meta.stage)?.[1])
    || 'casting';

  // ---------- 头部 ----------
  const briefBox = el('div', { class: 'small dim', style: { whiteSpace: 'pre-wrap', margin: '6px 0 0' } }, d.brief);
  const editBrief = () => {
    const ta = el('textarea', {}, d.brief);
    modal({
      title: '编辑故事梗概(brief —— 全片唯一人工输入)',
      body: el('div', {}, ta, el('div', { class: 'small faint', style: { marginTop: '8px' } }, '保存后已完成的阶段不会自动重做;需要时到对应面板 force 重跑。')),
      actions: [
        { label: '取消', kind: 'ghost', onclick: c => c() },
        { label: '保存', kind: 'primary', onclick: async c => {
          try { const r = await api.post(`/api/projects/${name}/brief`, { brief: ta.value });
            clear(briefBox); briefBox.append(ta.value.trim()); c(); toast('brief 已保存:' + r.warning, 'ok', 6000);
          } catch (e) { toast(e.message, 'bad'); } } },
      ],
    });
  };

  const run = (op, extra = {}, confirmText = null, okLabel = '执行') => {
    const go = async () => {
      try {
        const r = await api.post(`/api/projects/${name}/run`, { op, ...extra });
        toast(`🚀 已提交:${r.job.title}`, 'ok');
        refresh();
      } catch (e) {
        if (e.status === 409) toast(`⏳ ${e.message} —— 顶部任务条可看实时进度;完成后自动解锁`, 'warn', 8000);
        else toast(`提交失败:${e.message}`, 'bad', 6000);
      }
    };
    if (confirmText) confirmModal(TABS.find(t => t[1] === activeTab)?.[2] || op, confirmText, go, okLabel);
    else go();
  };

  // ---------- 步进器 ----------
  const stepper = el('div', { class: 'stepper' });
  // ---------- 忙时任务条 ----------
  const busyBox = el('div', {});
  const busyLogLines = [];
  let busyJobId = null;

  function paintBusy() {
    clear(busyBox);
    const j = d.busy;
    if (!j) return;
    busyJobId = j.id;
    busyLogLines.length = 0;
    const gateBtns = j.status === 'awaiting'
      ? [el('button', { class: 'btn primary sm', onclick: async () => {
          try { await api.post(`/api/jobs/${j.id}/resume`); toast('已放行,流水线继续', 'ok'); }
          catch (e) { toast(e.message, 'bad'); } } }, '▶ 放行继续'),
         el('button', { class: 'btn danger sm', onclick: () => api.post(`/api/jobs/${j.id}/cancel`).catch(e => toast(e.message, 'bad')) }, '取消流水线')]
      : (j.status === 'running' && j.pausable
        ? [el('button', { class: 'btn danger sm', onclick: () => api.post(`/api/jobs/${j.id}/cancel`).catch(e => toast(e.message, 'bad')) }, '在下一阶段间隙取消')]
        : []);
    const failing = (j.meta?.failing || []);
    busyBox.append(el('div', { class: 'card accent' },
      el('div', { class: 'spread' },
        el('div', { class: 'row' }, statusChip(j.status), el('b', {}, j.title),
          j.meta?.stage_label ? el('span', { class: 'chip info' }, j.meta.stage_label) : null),
        el('div', { class: 'row' }, ...gateBtns)),
      j.status === 'awaiting' ? el('div', { class: 'small', style: { margin: '6px 0' } },
        el('span', { class: 'warn', style: { color: 'var(--warn)' } }, '⏸ '), j.meta?.note || '等待人工放行') : null,
      failing.length ? el('div', { class: 'small dim' }, '未过镜头:',
        failing.map(f => el('span', { class: 'chip bad', style: { margin: '2px 4px' }, title: f.advice }, f.case))) : null,
      el('div', { style: { marginTop: '8px' } }, busyLogEl)));
  }
  const busyLogEl = el('div', { class: 'joblog', style: { maxHeight: '180px' } }, '(等待输出…)');

  // ---------- 面板切换 ----------
  const tabBox = el('div', {});
  const ctx = {
    get d() { return d; }, name, run, refresh,
    setTab: (t) => { activeTab = t; paintTabs(); },
  };
  function paintTabs() {
    // 步进器
    clear(stepper);
    for (const [k, tabName, label, mod] of TABS) {
      const done = k && d.stages[k];
      const isRunning = d.busy?.meta?.stage === k;
      const isAwait = d.busy?.status === 'awaiting' && d.busy?.meta?.gate === `${k}_done`;
      const cls = ['step', activeTab === tabName ? 'active' : '',
        done ? 'done' : '', isRunning ? 'running' : '', isAwait ? 'awaiting' : ''].filter(Boolean).join(' ');
      stepper.append(el('div', { class: cls, onclick: () => { activeTab = tabName; paintTabs(); } },
        el('span', { class: 'num' }, done ? '✓' : '○'), label,
        isRunning ? ' ⟳' : isAwait ? ' ⏸' : ''));
    }
    // 面板
    if (tabBox.firstChild?._dispose) tabBox.firstChild._dispose();
    clear(tabBox);
    const mod = TABS.find(t => t[1] === activeTab)[3];
    const node = mod(ctx);
    tabBox.append(node);
  }

  function paintHeader(rootHeader) {
    clear(rootHeader);
    rootHeader.append(
      el('div', { class: 'spread' },
        el('div', {},
          el('h1', {}, d.script?.title_cn || name, el('span', { class: 'faint', style: { fontSize: '13px', marginLeft: '8px' } }, name)),
          el('div', { class: 'small dim' }, `${d.shots} 镜 · 创建 ${d.created} · 5.04s/镜 · 1344×768 → 竖版1080×1920`)),
        el('div', { class: 'row' },
          el('button', { class: 'btn primary sm', disabled: !!d.busy,
            onclick: () => run('pipeline', { mode: 'stepwise' }, '分步流水线:每个 agent 完成后暂停等你放行,审片后必停。', '启动') }, '🧭 分步流水线'),
          el('button', { class: 'btn sm', disabled: !!d.busy,
            onclick: () => run('produce', { auto_retake: true }, '全自动:一次到底,自动重拍≤2轮,全片约1-2小时。', '开拍') }, '🎬 全自动'),
          el('button', { class: 'btn ghost sm', onclick: editBrief }, '✏️ brief'))),
      briefBox,
      stepper, busyBox);
  }

  const header = el('div', {});
  let refreshTimer = null;
  async function refresh() {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(async () => {
      try {
        d = await api.get(`/api/projects/${name}`);
        paintHeader(header); paintTabs();
      } catch { /* 项目可能被删 */ }
    }, 600);
  }

  paintHeader(header);
  paintTabs();
  paintBusy();
  root.append(header, tabBox);

  // ---------- 实时事件 ----------
  disposers.push(bus.on('job', (j) => {
    if (j.project !== name) return;
    d.busy = ['queued', 'running', 'awaiting'].includes(j.status) ? j : null;
    paintBusy();
    if (j.status === 'awaiting') { refresh(); }
    // 步进器上的阶段高亮即时刷新
    if (j.status === 'running' || j.status === 'awaiting') paintHeader(header);
  }));
  disposers.push(bus.on('log', (m) => {
    if (m.id !== busyJobId) return;
    busyLogLines.push(...m.lines);
    if (busyLogLines.length > 500) busyLogLines.splice(0, busyLogLines.length - 500);
    busyLogEl.textContent = busyLogLines.join('\n');
    busyLogEl.scrollTop = busyLogEl.scrollHeight;
  }));

  return {
    dispose: () => {
      disposers.forEach(f => f());
      clearTimeout(refreshTimer);
      if (tabBox.firstChild?._dispose) tabBox.firstChild._dispose();
    },
    onJob: () => {},
    refresh,
  };
}
