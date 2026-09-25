// assets.js —— 资产库:道具/场地跨项目复用(新增/编辑/删除);服化道阶段可预选
import { api } from '../api.js';
import * as bus from '../bus.js';
import { el, clear, toast, modal, confirmModal } from '../ui.js';

const KIND_LABEL = { scene: '场地', prop: '道具' };
const KIND_DESC = {
  scene: '封闭英文场景 DNA(必须含点光源);被预选后逐字进入每镜 prompt,跨项目复用。',
  prop: '中文名 + 英文描述;预选后成为该片的必用道具(视觉记忆点)。',
};

export default async function render(root) {
  let data = { scene: [], prop: [] };
  try { data = await api.get('/api/assets'); } catch (e) {
    root.append(el('div', { class: 'empty' }, '资产库加载失败:', e.message)); return;
  }

  const editAsset = (kind, asset = {}, onSaved) => {
    const nameI = el('input', { type: 'text', value: asset.name_cn || '', placeholder: kind === 'scene' ? '如:雨夜便利店' : '如:透明雨伞' });
    const dnaI = el('textarea', { placeholder: kind === 'scene'
      ? 'a small convenience store interior at night, cold white fluorescent tubes, warm neon sign glowing at the entrance…(英文,含点光源)'
      : 'a transparent umbrella with subtle rain droplets, catching neon reflections…(英文)' },
      asset.dna_en || asset.desc_en || '');
    const lightI = el('input', { type: 'text', value: asset.light_cn || '', placeholder: '冷白荧光+门口暖霓虹(场地专用,可空)' });
    const tagsI = el('input', { type: 'text', value: (asset.tags || []).join(' '), placeholder: '夜 室内 市井(空格分隔,≤6个)' });
    modal({
      title: `${asset.id ? '编辑' : '新增'}${KIND_LABEL[kind]}`,
      body: el('div', {},
        el('div', { class: 'small dim', style: { marginBottom: '10px' } }, KIND_DESC[kind]),
        el('label', { class: 'field' }, el('span', {}, '中文名(必填)'), nameI),
        kind === 'scene' ? el('label', { class: 'field' }, el('span', {}, '灯光说明(中文)'), lightI) : null,
        el('label', { class: 'field' }, el('span', {}, kind === 'scene' ? '场景 DNA dna_en(必填,英文)' : '道具描述 desc_en(必填,英文)'), dnaI),
        el('label', { class: 'field' }, el('span', {}, '标签'), tagsI)),
      actions: [
        { label: '取消', kind: 'ghost', onclick: c => c() },
        { label: '保存', kind: 'primary', onclick: async c => {
          const body = { kind, asset: { ...asset, name_cn: nameI.value.trim(),
            [kind === 'scene' ? 'dna_en' : 'desc_en']: dnaI.value.trim(),
            light_cn: lightI.value.trim(), tags: tagsI.value.trim().split(/\s+/).filter(Boolean) } };
          try { await api.post('/api/assets', body); c(); toast('已保存', 'ok'); onSaved?.(); }
          catch (e) { toast(e.message, 'bad', 6000); }
        } },
      ],
    });
  };

  const delAsset = (kind, a, onDone) => confirmModal(`删除${KIND_LABEL[kind]} ${a.name_cn}`,
    '已预选该资产的项目在下次跑服化道时会自动跳过它。', async () => {
      try {
        await api.del(`/api/assets/${kind}/${encodeURIComponent(a.id)}`);
        toast('已删除', 'ok'); onDone();
      } catch (e) { toast(e.message, 'bad'); }
    }, '删除');

  const container = el('div', {});

  function paint() {
    clear(container);
    for (const kind of ['scene', 'prop']) {
      const list = data[kind] || [];
      const section = el('div', {},
        el('div', { class: 'spread' },
          el('div', {},
            el('h2', {}, `${kind === 'scene' ? '🏞' : '🎒'} ${KIND_LABEL[kind]}库(${list.length})`),
            el('p', { class: 'page-sub', style: { margin: 0 } }, KIND_DESC[kind])),
          el('button', { class: 'btn primary sm', onclick: () => editAsset(kind, {}, paint) }, `＋ 新增${KIND_LABEL[kind]}`)));
      if (!list.length) {
        section.append(el('div', { class: 'card empty' },
          `还没有${KIND_LABEL[kind]} —— 手动新增,或跑一次服化道 agent 自动归档新场景/道具`));
      } else {
        const grid = el('div', { class: 'grid cols2' });
        for (const a of list) {
          grid.append(el('div', { class: 'card' },
            el('div', { class: 'spread' },
              el('div', { class: 'row' },
                el('b', {}, a.name_cn),
                ...(a.tags || []).map(t => el('span', { class: 'chip' }, t))),
              el('div', { class: 'row' },
                el('button', { class: 'btn ghost sm', onclick: () => editAsset(kind, a, paint) }, '✏️'),
                el('button', { class: 'btn danger sm', onclick: () => delAsset(kind, a, paint) }, '🗑'))),
            kind === 'scene' && a.light_cn ? el('div', { class: 'small', style: { margin: '4px 0' } }, '💡 ', a.light_cn) : null,
            el('pre', { class: 'box small', style: { maxHeight: '110px' } },
              kind === 'scene' ? a.dna_en : a.desc_en),
            a.source ? el('div', { class: 'small faint' }, `来自项目 ${a.source} · ${a.updated || ''}`) : null));
        }
        section.append(grid);
      }
      container.append(section);
    }
  }

  async function refresh() {
    try { data = await api.get('/api/assets'); } catch { return; }
    paint();
  }

  root.append(
    el('h1', {}, '资产库'),
    el('p', { class: 'page-sub' },
      '道具与场地的跨项目复用库(桌面/短剧资产库)。服化道 agent 每次产出会自动归档新资产;项目里可先挑场地/道具再生成,锁定项逐字复用。'),
    container);
  paint();

  const off = bus.on('assets', refresh);
  return { dispose: off, refresh };
}
