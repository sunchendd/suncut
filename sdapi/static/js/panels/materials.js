// materials.js —— ② 物料 agent 面板:场景DNA / 音乐块 / 道具 / 空镜
import { el } from '../ui.js';

export default function render(ctx) {
  const { d, run } = ctx;
  const m = d.materials || {};
  const box = el('div', {});

  box.append(el('div', { class: 'spread' },
    el('div', {},
      el('h2', {}, '场景物料'),
      el('p', { class: 'page-sub' },
        '场景 DNA(必须含点光源)、95BPM 统一音乐块、道具与空镜;DNA 由程序逐字拼进每镜 prompt,保证跨镜一致。')),
    el('button', { class: 'btn sm', disabled: !!d.busy,
      onclick: () => run('materials', { force: true }, '重新生成场景物料(后续编剧/分镜需 force 重跑)。') }, '↻ 重新生成')));

  const scenes = m.scenes || [];
  if (!scenes.length) { box.append(el('div', { class: 'card empty' }, '尚无物料 —— 先跑「场景物料」阶段')); return box; }

  const grid = el('div', { class: 'grid cols2' });
  for (const s of scenes) {
    grid.append(el('div', { class: 'card' },
      el('div', { class: 'spread' },
        el('h3', {}, s.id),
        el('span', { class: 'chip info' }, '点光源')),
      el('div', { class: 'small', style: { margin: '2px 0 6px' } }, '💡 ', s.light_cn || '-'),
      el('pre', { class: 'box small', style: { maxHeight: '120px' } }, s.dna_en || '-'),
      (s.props || []).length ? el('div', { class: 'row' },
        ...(s.props || []).map(p => el('span', { class: 'chip', title: p }, p.split('-')[0]))) : null));
  }
  box.append(grid);

  box.append(el('div', { class: 'card' },
    el('h3', {}, '🎵 全片统一音乐块(95 BPM)'),
    el('pre', { class: 'box small' }, m.music_en || '-'),
    el('div', { class: 'small dim' }, m.style_note_en || '')));

  const broll = m.b_roll || [];
  if (broll.length) box.append(el('div', { class: 'card' },
    el('h3', {}, '空镜 B-Roll(t2va 生成,无人脸风险)'),
    el('div', { class: 'row' }, ...broll.map(b => el('span', { class: 'chip' }, typeof b === 'string' ? b.slice(0, 60) : JSON.stringify(b).slice(0, 60))))));
  return box;
}
