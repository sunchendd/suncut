// pool.js —— 演员库:角色资料包浏览 + 补三视图 + 转台参考集
import { api, mediaUrl } from '../api.js';
import { el, toast, confirmModal } from '../ui.js';

const REF_LABEL = { closeup: '特写', front: '正身', side: '侧身' };

export default async function render(root) {
  let actors = [];
  try { actors = (await api.get('/api/pool')).actors; } catch (e) {
    root.append(el('div', { class: 'empty' }, '演员库加载失败:', e.message)); return;
  }

  const run = (char, op, text) => confirmModal(`${op === 'buildrefs' ? '补参考图' : '转台参考集'} · ${char}`,
    text, async () => {
      try {
        const r = await api.post(`/api/pool/${encodeURIComponent(char)}/run`, { op });
        toast(`🚀 已提交:${r.job.title}`, 'ok');
        setTimeout(() => location.hash = '#/jobs', 600);
      } catch (e2) { toast(`提交失败:${e2.message}`, 'bad', 6000); }
    });

  root.append(
    el('h1', {}, '演员库'),
    el('p', { class: 'page-sub' },
      `本地工坊共 ${actors.length} 名演员(${actors.filter(a => a.complete).length} 名三视图齐全可直接开拍)。资料包=角色DNA+三视图;缺图自动 Qwen 补图×3种子VLM选优;写实场景转台收益有限,按需使用。`));

  if (!actors.length) { root.append(el('div', { class: 'card empty' }, '演员库为空')); return; }
  const grid = el('div', { class: 'grid cols3' });
  for (const a of actors) {
    grid.append(el('div', { class: 'card' },
      el('div', { class: 'spread' },
        el('b', {}, a.name),
        el('span', { class: `chip ${a.complete ? 'ok' : 'warn'}` }, a.complete ? '可开拍' : '资料不全')),
      el('div', { class: 'img-row', style: { marginTop: '8px' } },
        Object.entries(REF_LABEL).map(([k, label]) => a.refs?.[k]
          ? el('div', {}, el('img', { class: 'thumb', src: mediaUrl(a.refs[k]), loading: 'lazy' }), el('div', { class: 'img-cap' }, label))
          : el('div', { class: 'card empty', style: { padding: '26px 0', margin: '0' } }, label + '缺'))),
      el('details', { style: { marginTop: '8px' } },
        el('summary', { class: 'small dim' }, '角色 DNA'),
        el('pre', { class: 'box small' }, `face:   ${a.face_dna || '-'}\noutfit: ${a.outfit_dna || '-'}\nseed:   ${a.seed ?? '-'}`)),
      el('div', { class: 'row', style: { marginTop: '6px' } },
        el('button', { class: 'btn sm', onclick: () => run(a.name, 'buildrefs',
          `用 Qwen 为 ${a.name} 生成特写并补齐三视图(每张分钟级,GPU 任务)。`) }, '🧩 补三视图'),
        el('button', { class: 'btn ghost sm', onclick: () => run(a.name, 'turntable',
          `t2va 转台视频抽帧替换 02/03 参考图(自动备份原图)。`) }, '🔄 转台参考集'))));
  }
  root.append(grid);
  return {};
}
