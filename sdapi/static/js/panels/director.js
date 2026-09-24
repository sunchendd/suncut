// director.js —— ⑤ 导演 agent 面板:成片镜头 + 重拍/重生成 + infer 日志
import { api, mediaUrl, fmtBytes } from '../api.js';
import { el, modal } from '../ui.js';
import { retakeModal, regenModal, videoModal } from './actions.js';

export default function render(ctx) {
  const { d, name, run, refresh } = ctx;
  const box = el('div', {});

  box.append(el('div', { class: 'spread' },
    el('div', {},
      el('h2', {}, '导演开拍'),
      el('p', { class: 'page-sub' },
        'Sol-H3 ref2va(有人物)/t2va(空镜)分批生成,缺镜自动重跑×2,断点续跑复用已完成镜头。草稿 ~70-120s/镜。')),
    el('div', { class: 'row' },
      el('button', { class: 'btn sm', disabled: !!d.busy,
        onclick: () => run('generate', { force: false }, '补拍缺失镜头(已有镜头不重跑)。', '补拍') },
        '▶ 补拍缺镜'),
      el('button', { class: 'btn sm', disabled: !!d.busy,
        onclick: () => run('generate', { force: true }, '全片重拍:忽略已有产物,全部重新生成(会作废旧审片)。') }, '↻ 全片重拍'))));

  const cases = d.cases.filter(c => c.video || c.takes.length);
  if (!cases.length) { box.append(el('div', { class: 'card empty' }, '尚无视频 —— 先跑「导演开拍」')); return box; }

  for (const c of cases) {
    const takeRows = (c.takes || []).map((t, i) => {
      const play = el('a', { href: '#', onclick: (e) => { e.preventDefault(); videoModal(`${c.case} take#${i + 1}`, t.mp4); } }, '播放');
      return el('tr', {},
        el('td', {}, `#${i + 1}`),
        el('td', { class: 'mono small' }, t.seed),
        el('td', { class: 'small', style: { maxWidth: '260px' } }, t.advice || '(仅换seed)'),
        el('td', {}, t.scores ? `${t.scores.identity}/${t.scores.action}/${t.scores.composition}` : el('span', { class: 'faint' }, '未复审')),
        el('td', {}, play));
    });
    const takesTable = (c.takes || []).length ? el('table', { class: 'tbl small' },
      el('thead', {}, el('tr', {}, el('th', {}, '条'), el('th', {}, 'seed'), el('th', {}, '重拍依据'), el('th', {}, '三维分'), el('th', {}, ''))),
      el('tbody', {}, ...takeRows)) : null;
    box.append(el('div', { class: 'card' },
      el('div', { class: 'spread' },
        el('div', { class: 'row' },
          el('span', { class: 'chip acc' }, c.case),
          el('span', { class: `chip ${c.task === 'ref2va' ? 'info' : ''}` }, c.task || '?'),
          el('span', { class: 'chip' }, `seed ${c.seed ?? '-'}`),
          (c.takes || []).length ? el('span', { class: 'chip warn' }, `重拍×${c.takes.length}`) : null),
        el('div', { class: 'row' },
          el('button', { class: 'btn sm', onclick: () => retakeModal(name, c, refresh, c.review?.advice_cn || '') }, '🎥 重拍'),
          el('button', { class: 'btn sm', onclick: () => regenModal(name, c, refresh) }, '💎 重生成'))),
      el('video', { src: mediaUrl(c.video), controls: '', preload: 'metadata', style: { maxHeight: '300px' } }),
      takesTable));
  }

  // ---- infer 日志 ----
  if (d.gen_logs?.length) {
    const logCard = el('div', { class: 'card' }, el('h3', {}, 'infer 生成日志(runtime)'));
    d.gen_logs.slice(-8).reverse().forEach(g => {
      logCard.append(el('div', { class: 'row small', style: { padding: '2px 0' } },
        el('a', { href: '#', onclick: async (e) => { e.preventDefault();
          try { const r = await api.get(`/api/projects/${name}/log/${g.name.replace(/^gen-|\.log$/g, '')}`);
            modal({ title: g.name, wide: true, body: el('pre', { class: 'box', style: { maxHeight: '60vh' } }, r.lines.join('\n')) });
          } catch (err) { /* 日志可能轮转 */ } } }, g.name),
        el('span', { class: 'faint' }, `${g.mtime} · ${fmtBytes(g.size)}`)));
    });
    box.append(logCard);
  }
  return box;
}
