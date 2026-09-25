// casting.js —— ① 招聘 agent 面板:选角结果 + 手动选角 + 演员资料包 + 补图
import { api, mediaUrl } from '../api.js';
import { el, toast, modal } from '../ui.js';

const REF_LABEL = { closeup: '特写', front: '正身', side: '侧身' };

// ---------- 手动选角 modal:演员卡勾选(1-2 人)+ 角色名 ----------
function manualCastModal(ctx) {
  const { d, name } = ctx;
  const m = modal({ title: '🖐 手动选角 —— 从演员库挑人', body: el('div', {}, '加载演员库…'), actions: [] });
  const mBody = m.back.querySelector('.modal-body');
  const mFoot = m.back.querySelector('.modal-foot');

  api.get('/api/pool').then(r => {
    const actors = (r.actors || []);
    const picked = new Map();          // char -> {story_role, wardrobe_note}
    const already = new Map((d.cast?.cast || []).map(c => [c.char, c.story_role]));

    const paintFoot = () => {
      mFoot.textContent = '';
      mFoot.append(
        el('button', { class: 'btn ghost', onclick: m.close }, '取消'),
        el('button', { class: 'btn primary', onclick: async () => {
          if (!picked.size) { toast('至少选 1 名演员', 'warn'); return; }
          const cast = [...picked.entries()].map(([char, v]) => ({
            story_role: v.story_role || (picked.size === 1 ? '主角' : '主角'),
            char, reason: '人工指定', wardrobe_note: v.wardrobe_note }));
          try {
            const r2 = await api.post(`/api/projects/${name}/cast`, { cast });
            m.close();
            toast(`🚀 已提交:${r2.job.title}(缺三视图会自动补图)`, 'ok');
            ctx.refresh();
          } catch (e) { toast(e.message, 'bad', 6000); }
        } }, `✅ 定选(${picked.size})`));
    };

    const paint = () => {
      mBody.textContent = '';
      mBody.append(el('div', { class: 'small dim', style: { marginBottom: '8px' } },
        `勾选 1-2 名演员(单镜≤2 人是硬约束);资料不全的也可选,提交后自动补三视图。当前选角:`,
        el('b', {}, [...already.keys()].join('、') || '无')));
      const grid = el('div', { class: 'grid cols3', style: { maxHeight: '52vh', overflowY: 'auto' } });
      for (const a of actors) {
        const roleI = el('input', { type: 'text', value: already.get(a.name) || '', placeholder: '主角', style: { width: '72px' } });
        roleI.onclick = e => e.stopPropagation();
        roleI.oninput = () => { if (picked.has(a.name)) picked.get(a.name).story_role = roleI.value.trim(); };
        const card = el('div', { class: `card ${picked.has(a.name) ? 'accent' : ''}`, style: { cursor: 'pointer' } },
          el('div', { class: 'spread' },
            el('b', { class: 'small' }, a.name),
            el('span', { class: `chip ${a.complete ? 'ok' : 'warn'}` }, a.complete ? '可开拍' : '资料不全')),
          a.refs?.closeup ? el('img', { class: 'thumb', src: mediaUrl(a.refs.closeup), loading: 'lazy' })
            : el('div', { class: 'empty', style: { padding: '26px 0', margin: '6px 0', background: 'var(--bg)', borderRadius: '8px' } }, '无特写'),
          el('div', { class: 'small dim', style: { maxHeight: '42px', overflow: 'hidden' } }, (a.face_dna || '').slice(0, 60) + '…'),
          picked.has(a.name)
            ? el('label', { class: 'row small', style: { marginTop: '6px' } }, '角色名 ', roleI)
            : null);
        card.onclick = () => {
          if (picked.has(a.name)) picked.delete(a.name);
          else {
            if (picked.size >= 2) { toast('最多 2 名(单镜≤2 人)', 'warn'); return; }
            picked.set(a.name, { story_role: roleI.value.trim() });
          }
          paint();
        };
        grid.append(card);
      }
      mBody.append(grid);
      paintFoot();
    };
    paint();
  }).catch(e => { mBody.textContent = '演员库加载失败:' + e.message; });
}

export default function render(ctx) {
  const { d, name, run } = ctx;
  const cast = d.cast?.cast || [];
  const box = el('div', {});

  box.append(el('div', { class: 'spread' },
    el('div', {},
      el('h2', {}, '招聘选角'),
      el('p', { class: 'page-sub' },
        '从本地演员库为故事选 1-2 名演员(单镜≤2人是硬约束);可让 agent 智能选,也可手动指定;资料包缺三视图时自动用 Qwen 补图×3种子 + VLM 选优。')),
    el('div', { class: 'row' },
      el('button', { class: 'btn primary sm', disabled: !!d.busy, onclick: () => manualCastModal(ctx) }, '🖐 手动选角'),
      el('button', { class: 'btn sm', disabled: !!d.busy,
        onclick: () => run('cast', { force: true }, '重新招聘会重新选角(可能换演员),后续阶段需 force 重跑才生效。') }, '🤖 让 agent 重新选'),
      el('a', { class: 'btn ghost sm', href: '#/pool' }, '🎭 浏览演员库'))));

  if (!cast.length) {
    box.append(el('div', { class: 'card empty' }, '尚无选角结果 —— 手动选角,或跑「招聘选角」阶段'));
    return box;
  }

  for (const c of cast) {
    const p = c.profile || {};
    const refs = p.refs || {};
    box.append(el('div', { class: 'card' },
      el('div', { class: 'spread' },
        el('div', {},
          el('h3', {}, c.story_role, ' ', el('span', { class: 'chip acc' }, c.char),
            (c.reason === '人工指定' ? el('span', { class: 'chip', style: { marginLeft: '6px' } }, '🖐 手动') : null)),
          el('div', { class: 'small dim' }, '选角理由:', c.reason || '-')),
        el('span', { class: 'chip' }, `seed ${p.seed ?? '-'}`)),
      el('div', { class: 'small', style: { margin: '6px 0' } }, '服装备注:', c.wardrobe_note || '-'),
      el('details', { style: { margin: '4px 0' } },
        el('summary', { class: 'small dim' }, '角色 DNA(锁定跨镜一致性的关键,LLM 不许改写)'),
        el('pre', { class: 'box small' }, `face:   ${p.face_dna || '-'}\noutfit: ${p.outfit_dna || '-'}`)),
      el('div', { class: 'img-row', style: { marginTop: '6px' } },
        Object.entries(REF_LABEL).map(([k, label]) => refs[k]
          ? el('div', {}, el('img', { class: 'thumb', src: mediaUrl(refs[k]), loading: 'lazy' }),
            el('div', { class: 'img-cap' }, label))
          : el('div', { class: 'card empty', style: { padding: '20px 0' } }, `${label}缺失`)))));
  }
  return box;
}
