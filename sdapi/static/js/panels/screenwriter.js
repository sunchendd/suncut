// screenwriter.js —— ③ 编剧 agent 面板:剧本 + 自评四维 + 旁白SRT
import { mediaUrl } from '../api.js';
import { el, scoreBars } from '../ui.js';

const CRIT = { hook: '开场钩子', arc: '情绪弧线', narration: '旁白质量', visual: '画面感' };

export default function render(ctx) {
  const { d, name, run } = ctx;
  const s = d.script || {};
  const box = el('div', {});

  box.append(el('div', { class: 'spread' },
    el('div', {},
      el('h2', {}, '编剧'),
      el('p', { class: 'page-sub' },
        'glm-5.3 出稿 → flash 自评(hook/arc/narration/visual 四维,任一<7 带反馈重写,≤2轮);硬约束前置:5.04s/镜、动作≤3节点、旁白≤25字、禁手部特写/正面说话。')),
    el('div', { class: 'row' },
      (d.stages.script ? el('a', { class: 'btn ghost sm', href: mediaUrl(`${d.project_dir}/narration.srt`, true) }, '⬇ 旁白字幕 SRT') : null),
      el('button', { class: 'btn sm', disabled: !!d.busy,
        onclick: () => run('script', { force: true }, '重写剧本(自评-修订闭环会重新跑;分镜及之后需 force 重跑)。') }, '↻ 重写剧本'))));

  if (!s.shots) { box.append(el('div', { class: 'card empty' }, '尚无剧本 —— 先跑「编剧」阶段')); return box; }

  box.append(el('div', { class: 'card accent' },
    el('div', { class: 'spread' },
      el('div', {},
        el('h3', {}, s.title_cn || '(未命名)'),
        el('div', { class: 'dim' }, s.logline || '')),
      s.ending_memory ? el('span', { class: 'chip acc' }, '留白结尾') : null),
    s.ending_memory ? el('div', { class: 'small dim', style: { marginTop: '4px' } }, '结尾记忆点:', s.ending_memory) : null));

  if (s.critique) box.append(el('div', { class: 'card' },
    el('h3', {}, '自评四维(达标线 7)'),
    scoreBars(s.critique)));

  const bodyRows = (s.shots || []).map(sh => {
    const detailCell = el('td', { style: { maxWidth: '420px' } },
      el('details', {},
        el('summary', { class: 'small dim' }, (sh.shot_en || '').slice(0, 46) + '…'),
        el('div', { class: 'small' }, el('b', {}, 'shot_en: '), sh.shot_en || ''),
        el('div', { class: 'small', style: { marginTop: '4px' } }, el('b', {}, 'action_en: '), sh.action_en || '')));
    return el('tr', {},
      el('td', {}, el('span', { class: 'chip' }, sh.id)),
      el('td', {}, sh.scene || '-'),
      el('td', {}, (sh.cast || []).join('、') || '空镜'),
      el('td', {}, sh.emotion_cn || '-'),
      el('td', { style: { maxWidth: '200px' } }, sh.narration_cn || ''),
      detailCell);
  });
  const tbl = el('table', { class: 'tbl' },
    el('thead', {}, el('tr', {},
      el('th', {}, '镜'), el('th', {}, '场景'), el('th', {}, '出场'), el('th', {}, '情绪'),
      el('th', {}, '旁白(≤25字)'), el('th', {}, '画面与动作'))),
    el('tbody', {}, ...bodyRows));
  box.append(el('div', { class: 'card', style: { padding: '6px 10px' } },
    el('div', { class: 'scroll-x' }, tbl)));
  return box;
}
