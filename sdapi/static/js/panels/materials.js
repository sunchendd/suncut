// materials.js —— ② 服化道 agent 面板:场景DNA / 音乐块 / 道具 / 空镜 / 资产库预选
import { api } from '../api.js';
import { el, toast, modal } from '../ui.js';

// ---------- 从资产库预选场地/道具 ----------
function pickAssetsModal(ctx) {
  const { d, name } = ctx;
  const m = modal({ title: '📦 预选场地 / 道具(资产库)', body: el('div', {}, '加载资产库…'), actions: [] });
  const mBody = m.back.querySelector('.modal-body');
  const mFoot = m.back.querySelector('.modal-foot');

  api.get('/api/assets').then(r => {
    const picked = {
      scenes: new Set((d.assets_pick?.scenes) || []),
      props: new Set((d.assets_pick?.props) || []),
    };
    const paint = () => {
      mBody.textContent = '';
      mBody.append(el('div', { class: 'small dim', style: { marginBottom: '8px' } },
        '锁定的场地 DNA 会逐字进入每镜 prompt(不再让 LLM 改写),只补足缺的场景数;选中的道具成为必用道具。服化道已生成的话需 force 重跑才生效。'));
      for (const [kind, label, max] of [['scenes', '🏞 场地(≤4)', 4], ['props', '🎒 道具(≤6)', 6]]) {
        const list = r[kind === 'scenes' ? 'scene' : 'prop'] || [];
        const wrap = el('div', { style: { marginBottom: '10px' } }, el('b', { class: 'small' }, `${label} 已选 ${picked[kind].size}`));
        if (!list.length) {
          wrap.append(el('div', { class: 'small faint' }, '资产库为空 —— 可先去「资产库」页手动添加'));
        } else {
          const grid = el('div', { class: 'grid cols2', style: { maxHeight: '34vh', overflowY: 'auto' } });
          for (const a of list) {
            const on = picked[kind].has(a.id);
            const card = el('div', { class: `card ${on ? 'accent' : ''}`, style: { cursor: 'pointer', padding: '8px 10px' } },
              el('div', { class: 'spread' },
                el('b', { class: 'small' }, on ? '✅ ' : '', a.name_cn),
                el('span', { class: 'faint small' }, a.source ? `来自 ${a.source}` : '手动')),
              el('div', { class: 'small dim', style: { maxHeight: '40px', overflow: 'hidden' } },
                (kind === 'scenes' ? a.dna_en : a.desc_en || '').slice(0, 90) + '…'));
            card.onclick = () => {
              if (picked[kind].has(a.id)) picked[kind].delete(a.id);
              else {
                if (picked[kind].size >= max) { toast(`最多选 ${max} 个`, 'warn'); return; }
                picked[kind].add(a.id);
              }
              paint();
            };
            grid.append(card);
          }
          wrap.append(grid);
        }
        mBody.append(wrap);
      }
      mFoot.textContent = '';
      mFoot.append(
        el('button', { class: 'btn ghost', onclick: m.close }, '取消'),
        el('button', { class: 'btn primary', onclick: async () => {
          try {
            const r2 = await api.post(`/api/projects/${name}/assets`,
              { scenes: [...picked.scenes], props: [...picked.props] });
            m.close();
            toast(r2.warning ? `已保存预选 —— ${r2.warning}` : '已保存预选(跑服化道时生效)', r2.warning ? 'warn' : 'ok', 6000);
            ctx.refresh();
          } catch (e) { toast(e.message, 'bad', 6000); }
        } }, '💾 保存预选'));
    };
    paint();
  }).catch(e => { mBody.textContent = '资产库加载失败:' + e.message; });
}

export default function render(ctx) {
  const { d, run } = ctx;
  const m = d.materials || {};
  const box = el('div', {});
  const picks = d.assets_pick || {};

  box.append(el('div', { class: 'spread' },
    el('div', {},
      el('h2', {}, '服化道'),
      el('p', { class: 'page-sub' },
        '场景 DNA(必须含点光源)、95BPM 统一音乐块、道具与空镜;可先从资产库预选场地/道具(锁定复用);产出自动归档回资产库。')),
    el('div', { class: 'row' },
      el('button', { class: 'btn primary sm', disabled: !!d.busy, onclick: () => pickAssetsModal(ctx) },
        `📦 预选资产${(picks.scenes?.length || picks.props?.length) ? `(${picks.scenes?.length || 0}场/${picks.props?.length || 0}道)` : ''}`),
      el('a', { class: 'btn ghost sm', href: '#/assets' }, '🗄 管理资产库'),
      el('button', { class: 'btn sm', disabled: !!d.busy,
        onclick: () => run('materials', { force: true }, '重新生成服化道(预选锁定项保持不变;后续编剧/分镜需 force 重跑)。') }, '↻ 重新生成'))));

  const scenes = m.scenes || [];
  if (!scenes.length) { box.append(el('div', { class: 'card empty' }, '尚无服化道 —— 先跑「服化道」阶段')); return box; }

  const grid = el('div', { class: 'grid cols2' });
  for (const s of scenes) {
    grid.append(el('div', { class: 'card' },
      el('div', { class: 'spread' },
        el('div', { class: 'row' },
          el('h3', {}, s.id, ' ', el('span', { class: 'small' }, s.name_cn || '')),
          s.from_lib ? el('span', { class: 'chip acc' }, '库锁定') : null),
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

  if (m.archived && ((m.archived.scenes?.length) || (m.archived.props?.length))) {
    box.append(el('div', { class: 'card accent' },
      el('h3', {}, '🗄 本轮自动归档入资产库'),
      el('div', { class: 'row' },
        ...(m.archived.scenes || []).map(a => el('span', { class: 'chip ok' }, '场地 ' + a.name_cn)),
        ...(m.archived.props || []).map(a => el('span', { class: 'chip ok' }, '道具 ' + a.name_cn)))));
  }
  return box;
}
