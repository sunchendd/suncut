// casting.js —— ① 招聘 agent 面板:选角结果 + 演员资料包 + 补图
import { mediaUrl } from '../api.js';
import { el } from '../ui.js';

const REF_LABEL = { closeup: '特写', front: '正身', side: '侧身' };

export default function render(ctx) {
  const { d, name, run } = ctx;
  const cast = d.cast?.cast || [];
  const box = el('div', {});

  box.append(el('div', { class: 'spread' },
    el('div', {},
      el('h2', {}, '招聘选角'),
      el('p', { class: 'page-sub' },
        '从本地演员库为故事选 1-2 名演员(单镜≤2人是硬约束);资料包缺三视图时自动用 Qwen 补图×3种子 + VLM 选优。')),
    el('div', { class: 'row' },
      el('button', { class: 'btn sm', disabled: !!d.busy,
        onclick: () => run('cast', { force: true }, '重新招聘会重新选角(可能换演员),后续阶段需 force 重跑才生效。') }, '↻ 重新招聘'),
      el('a', { class: 'btn ghost sm', href: '#/pool' }, '🎭 浏览演员库'))));

  if (!cast.length) {
    box.append(el('div', { class: 'card empty' }, '尚无选角结果 —— 先跑「招聘选角」阶段'));
    return box;
  }

  for (const c of cast) {
    const p = c.profile || {};
    const refs = p.refs || {};
    box.append(el('div', { class: 'card' },
      el('div', { class: 'spread' },
        el('div', {},
          el('h3', {}, c.story_role, ' ', el('span', { class: 'chip acc' }, c.char)),
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
