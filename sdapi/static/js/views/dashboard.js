// dashboard.js —— 仪表盘:项目总览 + 新建 + 快捷开拍
import { api } from '../api.js';
import * as bus from '../bus.js';
import { el, clear, toast, modal, confirmModal } from '../ui.js';

const STAGES = [['cast', '招聘'], ['materials', '服化道'], ['script', '编剧'],
  ['storyboard', '分镜'], ['generate', '开拍'], ['review', '审片'], ['dub', '配音'], ['deliver', '交付']];

async function run(name, op, extra = {}) {
  try {
    const r = await api.post(`/api/projects/${name}/run`, { op, ...extra });
    toast(`🚀 已提交:${r.job.title}`, 'ok');
    location.hash = `#/project/${name}`;
  } catch (e) { toast(`提交失败:${e.message}`, 'bad'); }
}

export function newProjectModal() {
  const name = el('input', { type: 'text', placeholder: '英文/拼音,如 yedeng(唯一人工输入的名字)' });
  const brief = el('textarea', { placeholder: '一句话故事梗概。例:雨夜便利店的女孩,用便利贴回复每晚匿名留言的常客,直到最后一晚纸条上写着告别。' });
  const shots = el('input', { type: 'number', value: '4', min: '1', max: '12' });
  const ori = el('select', {},
    el('option', { value: 'landscape', selected: '' }, '横屏 16:9(推荐·原生画质)'),
    el('option', { value: 'portrait' }, '竖屏 9:16(裁切·清晰度降)'));
  const res = el('select', {},
    el('option', { value: '1080p', selected: '' }, '1080p'),
    el('option', { value: '720p' }, '720p(更快更小)'),
    el('option', { value: '480p' }, '480p(草稿预览)'));
  modal({
    title: '新建短剧项目',
    body: el('div', {},
      el('label', { class: 'field' }, el('span', {}, '项目名'), name),
      el('label', { class: 'field' }, el('span', {}, '故事梗概(一句话,决定全片基调)'), brief),
      el('div', { class: 'row' },
        el('label', { class: 'field', style: { flex: '1' } }, el('span', {}, '画幅'), ori),
        el('label', { class: 'field', style: { flex: '1' } }, el('span', {}, '分辨率'), res),
        el('label', { class: 'field', style: { width: '110px' } }, el('span', {}, '镜头数(1镜≈5s)'), shots))),
    actions: [
      { label: '取消', kind: 'ghost', onclick: (c) => c() },
      {
        label: '创建', kind: 'primary', onclick: async (c) => {
          try {
            await api.post('/api/projects', { name: name.value.trim(), brief: brief.value, shots: +shots.value, orientation: ori.value, resolution: res.value });
            c(); toast(`项目 ${name.value.trim()} 已创建`, 'ok');
            location.hash = `#/project/${name.value.trim()}`;
          } catch (e) { toast(e.message, 'bad'); }
        },
      },
    ],
  });
}

function projCard(p) {
  const stages = p.stages || {};
  const curIdx = STAGES.findIndex(([k]) => !stages[k]);
  return el('div', { class: 'card proj-card' },
    el('div', { class: 'spread' },
      el('div', {},
        el('div', { class: 'title' }, p.title || p.name, ' ', el('span', { class: 'faint small' }, `(${p.name})`)),
        el('div', { class: 'small dim' },
          `${p.shots} 镜 · ${p.created || ''}`, p.review_pass ? el('span', { class: 'chip ok', style: { marginLeft: '8px' } }, `审片 ${p.review_pass}`) : null)),
      p.busy ? el('span', { class: 'chip info' }, el('span', { class: 'status-dot running' }), p.busy.title) : null),
    el('div', { class: 'mini-steps' },
      STAGES.map(([k, label], i) => el('div', {
        class: `mini-step ${stages[k] ? 'done' : i === curIdx ? 'cur' : ''}`,
        title: label + (stages[k] ? ` ✓ ${stages[k]}` : ''),
      }))),
    el('div', { class: 'row small dim' },
      `更新 ${p.updated || '-'}`, `已生成 ${p.videos || 0} 镜`),
    el('div', { class: 'row', style: { marginTop: '10px' } },
      el('a', { class: 'btn primary sm', href: `#/project/${p.name}` }, '进入工作台'),
      el('button', {
        class: 'btn sm', disabled: !!p.busy,
        onclick: () => confirmModal('全自动开拍',
          `对「${p.title || p.name}」执行全自动流水线?含自动重拍≤2轮,全片约 1-2 小时(4镜)。`,
          () => run(p.name, 'produce', { auto_retake: true }), '开拍'),
      }, '🎬 全自动开拍'),
      el('button', {
        class: 'btn sm', disabled: !!p.busy,
        onclick: () => confirmModal('分步流水线',
          '分步模式:每个 agent 完成后暂停,等你审阅放行才继续;审片后必停一档。适合逐段把控质量。',
          () => run(p.name, 'pipeline', { mode: 'stepwise' }), '启动'),
      }, '🧭 分步流水线')));
}

export default async function render(root) {
  let data = null;
  try { data = await api.get('/api/overview'); } catch (e) { root.append(el('div', { class: 'empty' }, '加载失败:', e.message)); return; }

  const list = el('div', { class: 'grid cols2' });
  const paint = () => {
    clear(list);
    if (!data.projects.length) list.append(el('div', { class: 'empty', style: { gridColumn: '1/-1' } }, '还没有项目 —— 点右上角「新建项目」开始'));
    else data.projects.forEach(p => list.append(projCard(p)));
  };
  paint();

  root.append(
    el('div', { class: 'spread' },
      el('div', {}, el('h1', {}, '仪表盘'), el('p', { class: 'page-sub' }, '一句话梗概 → 竖版短剧:八个 agent 分工 + 本地出图出视频,人工只留质控位')),
      el('div', { class: 'row' },
        data.actors ? el('a', { class: 'chip', href: '#/pool', style: { textDecoration: 'none' } },
          `🎭 演员 ${data.actors.ready}/${data.actors.total} 可开拍`) : null,
        data.candidates ? el('a', { class: 'chip warn', href: '#/pool', style: { textDecoration: 'none' } },
          `⏳ 候选区 ${data.candidates} 人试镜中`) : null,
        el('button', { class: 'btn primary', onclick: newProjectModal }, '＋ 新建项目'))),
    list);

  // 任务事件频繁(每次状态推进一条),节流合并刷新;不用 rAF(后台标签页会挂起)
  let pending = false;
  const fetchOverview = () => {
    api.get('/api/overview').then(d => {
      data = d;
      if (!pending) { pending = true; setTimeout(() => { pending = false; paint(); }, 0); }
    }).catch(() => {});
  };
  let timer = null;
  const off = bus.on('job', () => {
    clearTimeout(timer);
    timer = setTimeout(fetchOverview, 800);
  });
  return {
    dispose: () => { off(); clearTimeout(timer); },
    refresh: fetchOverview,
  };
}
