// reviewer.js —— ⑥ 审片 agent 面板:三维分 + 抽帧对照 + 人工否决权(质控核心)
import { api, mediaUrl } from '../api.js';
import { el, toast, scoreBars } from '../ui.js';
import { retakeModal, videoModal } from './actions.js';

export default function render(ctx) {
  const { d, name, run, refresh } = ctx;
  const box = el('div', {});

  const rv = d.review || {};
  box.append(el('div', { class: 'spread' },
    el('div', {},
      el('h2', {}, '审片'),
      el('p', { class: 'page-sub' },
        'glm-4.5v 双次评审取均值(单次噪声±4),三维分≥7 判过;分数历史只升不降;人工保留否决权。')),
    el('div', { class: 'row' },
      d.review_stale ? el('span', { class: 'chip bad', title: '重拍/重生成后旧审片已作废,请重新审片' }, '⚠ 重拍后待复审') : null,
      rv.total ? el('span', { class: `chip ${!d.review_stale && rv.passed === rv.total ? 'ok' : 'warn'}` },
        `${rv.passed}/${rv.total} 过片`) : null,
      (rv.results || []).some(r => ['retake', 'fail'].includes(r.verdict)
          && !((d.human || {})[r.case] || {}).approved)
        ? el('button', { class: 'btn primary sm', disabled: !!d.busy,
            onclick: () => run('retake_failed', {},
              '按审片建议批量重拍全部未过镜(人工翻案的不算),逐镜外科手术改 dd+换 seed;完成后需重新审片。', '批量重拍') },
          '🔁 一键重拍未过镜') : null,
      el('button', { class: 'btn sm', disabled: !!d.busy,
        onclick: () => run('review', { force: true }, '强制重新审片(重抽帧+双次VLM评分,19s/镜)。') }, '↻ 重新审片'))));

  const cases = d.cases.filter(c => c.review || c.video);
  if (!cases.length) { box.append(el('div', { class: 'card empty' }, '尚无可审内容 —— 先完成导演开拍')); return box; }

  const humanMark = async (c, approved, note = '') => {
    try {
      await api.post(`/api/projects/${name}/review/human`, { case: c.case, approved, note });
      toast(approved ? `✅ 已人工通过 ${c.case}` : `⛔ 已否决 ${c.case} —— 建议立即发起重拍`, approved ? 'ok' : 'warn');
      if (!approved) retakeModal(name, c, refresh, c.review?.advice_cn || '');
      else refresh();
    } catch (e) { toast(e.message, 'bad'); }
  };

  for (const c of cases) {
    const r = c.review || {};
    const verdict = r.verdict || (c.gen_scores ? '未复审' : '未审');
    const human = c.human;
    box.append(el('div', { class: 'card', style: human && !human.approved ? { borderColor: 'var(--bad)' } : {} },
      el('div', { class: 'spread' },
        el('div', { class: 'row' },
          el('span', { class: 'chip acc' }, c.case),
          verdict === 'pass' ? el('span', { class: 'chip ok' }, '过') :
            ['retake', 'fail'].includes(verdict) ? el('span', { class: 'chip bad' }, '未过') :
              el('span', { class: 'chip warn' }, verdict),
          human ? el('span', { class: `chip ${human.approved ? 'ok' : 'bad'}` },
            human.approved ? '人工✓' : '人工否决') : null,
          (c.takes || []).length ? el('span', { class: 'chip' }, `历史条×${(c.takes || []).length + 1}`) : null),
        el('div', { class: 'row' },
          el('button', { class: 'btn sm done-btn', onclick: () => humanMark(c, true, '人工通过') }, '人工通过'),
          el('button', { class: 'btn danger sm', onclick: () => humanMark(c, false, c.review?.advice_cn || '人工否决') }, '⛔ 否决并重拍'))),
      el('div', { class: 'img-row', style: { margin: '10px 0' } },
        ...c.frames.map((f, i) => el('div', {},
          el('img', { class: 'thumb', src: mediaUrl(f), loading: 'lazy' }),
          el('div', { class: 'img-cap' }, `抽帧 f${i}`))),
        c.sheet ? el('div', {}, el('img', { class: 'thumb', src: mediaUrl(c.sheet), loading: 'lazy' }),
          el('div', { class: 'img-cap' }, 'contact sheet')) : null),
      el('div', { class: 'row', style: { margin: '8px 0' } },
        el('button', { class: 'btn ghost sm', onclick: () => videoModal(c.case, c.video) }, '▶ 播放视频'),
        r.tech ? el('span', { class: 'chip' }, `时长 ${r.tech.duration?.toFixed(2) || '?'}s · ${r.tech.has_audio ? '有音轨' : '⚠ 无音轨'}`) : null),
      scoreBars(r.identity != null ? r : c.gen_scores),
      (r.advice_cn || r.advice) ? el('div', { class: 'small', style: { margin: '6px 0 0', color: 'var(--warn)' } },
        '重拍建议:', r.advice_cn || r.advice) : null));
      const takeRows = [];
      if ((c.takes || []).some(t => t.scores)) {
        for (let i = 0; i < c.takes.length; i++) {
          const t = c.takes[i];
          const play = el('a', { href: '#', onclick: (e) => { e.preventDefault(); videoModal(`${c.case} take#${i + 1}`, t.mp4); } }, '播放');
          takeRows.push(el('tr', {},
            el('td', {}, `take#${i + 1}`), el('td', { class: 'mono' }, t.seed),
            el('td', {}, t.scores ? `${t.scores.identity}/${t.scores.action}/${t.scores.composition}` : '未评分'),
            el('td', {}, play)));
        }
        const tbody = el('tbody', {}, ...takeRows);
        box.append(el('details', { style: { marginTop: '6px' } },
          el('summary', { class: 'small dim' }, '条历史分数(只升不降)'),
          el('table', { class: 'tbl small' }, tbody)));
      }
  }
  return box;
}
