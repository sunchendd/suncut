// producer.js —— ⑦ 制片 agent 面板:选片交付 + 母版 + 报告 + 指标
import { api, mediaUrl, fmtBytes, fmtDur } from '../api.js';
import { el, toast, modal } from '../ui.js';
import { videoModal } from './actions.js';

export default function render(ctx) {
  const { d, name, run, refresh } = ctx;
  const box = el('div', {});
  const s = d.settings || {};
  const resTxt = `${s.orientation === 'landscape' ? '横屏' : '竖屏'} ${s.resolution || '1080p'}`;

  const subs = el('input', { type: 'checkbox', checked: '' });
  subs.style.accentColor = 'var(--acc, #4a9)';
  const doDeliver = () => run('deliver', { force: true, subs: subs.checked },
    `重新选片并交付(${resTxt};${subs.checked ? '烧录台词/旁白字幕;' : ''}配音产物自动混入)到 deliver/ 与桌面。`, '交付');

  box.append(el('div', { class: 'spread' },
    el('div', {},
      el('h2', {}, '制片交付'),
      el('p', { class: 'page-sub' },
        `按剧本顺序选每镜历史最佳条(全≥7优先)拼接 → ${resTxt} CRF17 → deliver/ 与桌面;配音师产物自动侧链混入;可勾选烧录字幕。`)),
    el('div', { class: 'row' },
      el('label', { class: 'row small', style: { gap: '4px', alignSelf: 'center' } },
        subs, '📝 自动字幕'),
      el('button', { class: 'btn primary sm', disabled: !!d.busy, onclick: doDeliver }, '📦 交付成片'),
      el('button', { class: 'btn sm', disabled: !!d.busy,
        onclick: () => run('master', { subs: subs.checked }, `母版链:ComfyUI SPAN×2 超分 → ${resTxt} → CRF14(~80s/镜,自动拉起 ComfyUI)。`, '生成母版') }, '💎 母版超分'))));

  // 选片表
  if (d.picks?.length) {
    box.append(el('div', { class: 'card', style: { padding: '6px 10px' } },
      el('h3', { style: { padding: '6px 4px 0' } }, '交付选条(每镜历史最佳)'),
      el('div', { class: 'scroll-x' },
        el('table', { class: 'tbl' },
          el('thead', {}, el('tr', {}, el('th', {}, '镜头'), el('th', {}, '选中条'), el('th', {}, '判定'))),
          el('tbody', {}, ...d.picks.map(p => el('tr', {},
            el('td', {}, el('span', { class: 'chip acc' }, p.case)),
            el('td', {}, el('a', { href: '#', onclick: (e) => { e.preventDefault(); videoModal(p.case, p.picked); } },
              p.picked.split('/').slice(-4, -2).join('/'))),
            el('td', {}, el('span', { class: `chip ${p.verdict === 'pass' ? 'ok' : 'warn'}` }, p.verdict || '-')))))))));
  }

  // 交付物
  const vids = d.deliverables.filter(f => f.name.endsWith('.mp4'));
  const imgs = d.deliverables.filter(f => /\.(jpg|png)$/i.test(f.name));
  const docs = d.deliverables.filter(f => /\.(md|srt|txt)$/i.test(f.name));

  if (!d.deliverables.length) {
    box.append(el('div', { class: 'card empty' }, '尚无交付物 —— 审片通过后点「交付成片」'));
  } else {
    if (vids.length) {
      const grid = el('div', { class: 'grid cols3' });
      for (const v of vids) {
        const isVertical = v.name.includes('竖版');
        grid.append(el('div', { class: 'card' },
          el('div', { class: 'spread' },
            el('b', { class: 'small' }, v.name),
            el('a', { class: 'btn ghost sm', href: mediaUrl(v.path, true) }, '⬇')),
          el('video', { src: mediaUrl(v.path), controls: '', preload: 'metadata',
            style: isVertical ? { maxHeight: '420px', margin: '0 auto' } : { maxHeight: '240px' } }),
          el('div', { class: 'img-cap' }, `${fmtBytes(v.size)} · ${v.mtime}`)));
      }
      box.append(el('h2', {}, '成片'), grid);
    }
    if (imgs.length) {
      const grid = el('div', { class: 'grid cols4' });
      for (const im of imgs.slice(0, 8)) {
        grid.append(el('div', { class: 'card' },
          el('img', { class: 'thumb', src: mediaUrl(im.path), loading: 'lazy' }),
          el('div', { class: 'img-cap' }, `${im.name} · ${fmtBytes(im.size)}`)));
      }
      box.append(el('h2', {}, '封面/图片'), grid);
    }
    if (docs.length) {
      const docCard = el('div', { class: 'card' }, el('h3', {}, '文档与字幕'));
      for (const doc of docs) {
        docCard.append(el('div', { class: 'row small', style: { padding: '3px 0' } },
          el('a', { href: '#', onclick: async (e) => { e.preventDefault();
            const r = await fetch(mediaUrl(doc.path)); const t = await r.text();
            modal({ title: doc.name, wide: true, body: el('pre', { class: 'box', style: { maxHeight: '60vh' } }, t.slice(0, 20000)) });
          } }, '📄 ', doc.name),
          el('a', { class: 'faint small', href: mediaUrl(doc.path, true) }, '下载'),
          el('span', { class: 'faint' }, fmtBytes(doc.size))));
      }
      box.append(el('h2', {}, '文档'), docCard);
    }
  }

  // 指标
  if (d.metrics_summary) {
    box.append(el('h2', {}, '制作指标'),
      el('div', { class: 'card' }, el('pre', { class: 'box', style: { margin: 0 } }, d.metrics_summary)));
  }
  return box;
}
