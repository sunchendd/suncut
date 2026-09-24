// pool.js —— 演员库:演员卡 + 签约主演/群演 + 候选区(试镜/重掷/签约入库)
import { api, mediaUrl } from '../api.js';
import * as bus from '../bus.js';
import { el, clear, toast, modal, confirmModal } from '../ui.js';

const REF_LABEL = { closeup: '特写', front: '正身', side: '侧身' };

export default async function render(root) {
  let actors = [];
  let candidates = [];
  try {
    [actors, candidates] = await Promise.all([
      api.get('/api/pool').then(r => r.actors),
      api.get('/api/audition').then(r => r.candidates)]);
  } catch (e) { root.append(el('div', { class: 'empty' }, '演员库加载失败:', e.message)); return; }

  const submitJob = async (url, body) => {
    try {
      const r = await api.post(url, body);
      toast(`🚀 已提交:${r.job.title}`, 'ok');
      return r;
    } catch (e) { toast(`提交失败:${e.message}`, 'bad', 6000); return null; }
  };

  // ---------- 签约主演:三步 modal ----------
  const signLead = () => {
    const req = el('textarea', { placeholder: '例:22岁左右,清冷书卷气的书店店员,秋日氛围感(年龄/气质/发型/服装方向,越具体越好)' });
    const count = el('input', { type: 'number', value: '3', min: '1', max: '8' });
    const m = modal({ title: '签约主演 —— 招聘要求 → 人设卡 → 试镜照', body: el('div', {}), actions: [] });
    const mBody = m.back.querySelector('.modal-body');
    const mFoot = m.back.querySelector('.modal-foot');

    let cards = [];
    const paintStep1 = () => {
      clear(mBody); clear(mFoot);
      mBody.append(
        el('div', { class: 'small dim', style: { marginBottom: '10px' } },
          '演员 agent 会先优化你的提示词,产出多张差异化人设卡(名字/定位/角色DNA/默认穿搭)——此步只调 LLM 不占 GPU,卡片可直接编辑。'),
        el('label', { class: 'field' }, el('span', {}, '招聘要求'), req),
        el('label', { class: 'field' }, el('span', {}, '候选人数'), count));
      const genBtn = el('button', { class: 'btn primary', onclick: async () => {
        if (!req.value.trim()) { toast('招聘要求不能为空', 'warn'); return; }
        genBtn.disabled = true; genBtn.textContent = '优化提示词中…';
        try {
          const r = await api.post('/api/audition/cards',
            { requirement: req.value, count: +count.value });
          cards = r.cards; paintStep2();
        } catch (e) { toast(e.message, 'bad', 6000); genBtn.disabled = false; genBtn.textContent = '✨ 生成人设卡'; }
      } }, '✨ 生成人设卡');
      mFoot.append(el('button', { class: 'btn ghost', onclick: m.close }, '取消'), genBtn);
    };

    const paintStep2 = () => {
      clear(mBody); clear(mFoot);
      mBody.append(el('div', { class: 'small dim', style: { marginBottom: '8px' } },
        `${cards.length} 张人设卡(可直接编辑;满意才生成试镜照,每人约 4 分钟 GPU)`));
      const list = el('div', {});
      const paintCards = () => {
        clear(list);
        cards.forEach((c, i) => {
          const nameI = el('input', { type: 'text', value: c.name });
          const posI = el('input', { type: 'text', value: c.positioning_cn || '' });
          const faceI = el('textarea', { style: { minHeight: '54px' } }, c.face_dna);
          const outfitI = el('textarea', { style: { minHeight: '44px' } }, c.outfit_dna);
          nameI.oninput = () => { c.name = nameI.value; };
          posI.oninput = () => { c.positioning_cn = posI.value; };
          faceI.oninput = () => { c.face_dna = faceI.value; };
          outfitI.oninput = () => { c.outfit_dna = outfitI.value; };
          list.append(el('div', { class: 'card' },
            el('div', { class: 'spread' },
              el('b', {}, `候选 ${i + 1}`),
              el('button', { class: 'btn danger sm', onclick: () => { cards.splice(i, 1); paintCards(); } }, '删卡')),
            el('label', { class: 'field' }, el('span', {}, '艺名'), nameI),
            el('label', { class: 'field' }, el('span', {}, '定位'), posI),
            el('label', { class: 'field' }, el('span', {}, 'FACE DNA(英文)'), faceI),
            el('label', { class: 'field' }, el('span', {}, '默认穿搭(英文)'), outfitI)));
        });
      };
      paintCards();
      mBody.append(list);
      mFoot.append(
        el('button', { class: 'btn ghost', onclick: paintStep1 }, '← 改要求'),
        el('button', { class: 'btn', onclick: async () => {
          try {
            const r = await api.post('/api/audition/cards', { requirement: req.value, count: +count.value });
            cards = r.cards; paintStep2();
          } catch (e) { toast(e.message, 'bad', 6000); }
        } }, '↻ 重新生成人设'),
        el('button', { class: 'btn primary', onclick: () => {
          if (!cards.length) { toast('至少保留一张卡', 'warn'); return; }
          m.close();
          submitJob('/api/audition/generate', { cards });
        } }, `📸 生成试镜照 ×${cards.length}`));
    };
    paintStep1();
  };

  // ---------- 签约群演 ----------
  const signExtras = () => {
    const count = el('input', { type: 'number', value: '5', min: '1', max: '10' });
    const dir = el('textarea', { placeholder: '气质方向(留空=自动多样化铺开)。例:市井夜市摊贩、校园路人、写字楼白领' }, '');
    const direct = el('input', { type: 'checkbox', checked: true });
    const info = el('div', { class: 'small dim', style: { marginTop: '8px' } });
    const upd = () => {
      info.textContent = direct.checked
        ? `直接全套入库:每人 三视图+三件套,约 13-15 分钟/人,共 ${+count.value || '?'} 人(挂机档,GPU 全局串行)`
        : `先出试镜照:每人 1 张锁脸特写(约 4 分钟/人),之后在候选区逐个勾选签约`;
    };
    direct.onchange = upd; count.oninput = upd; upd();
    modal({
      title: '签约群演(批量配角)',
      body: el('div', {},
        el('label', { class: 'field' }, el('span', {}, '数量'), count),
        el('label', { class: 'field' }, el('span', {}, '气质方向(可选)'), dir),
        el('label', { class: 'field', style: { display: 'flex', gap: '8px', alignItems: 'center' } },
          direct, el('span', {}, '跳过试镜,直接全套入库(挂机)')),
        info),
      actions: [
        { label: '取消', kind: 'ghost', onclick: c => c() },
        { label: '🚀 启动批量签约', kind: 'primary', onclick: c => {
          c();
          submitJob('/api/audition/batch',
            { requirement: dir.value.trim() || '多样化配角', count: +count.value, direct_sign: direct.checked });
        } },
      ],
    });
  };

  // ---------- 候选区 ----------
  const candBox = el('div', {});
  const paintCandidates = () => {
    clear(candBox);
    if (!candidates.length) return;
    candBox.append(el('h2', {}, `🎭 候选区(试镜中 ${candidates.length} 人)`),
      el('p', { class: 'page-sub' }, '候选对招聘 agent 不可见;「签约入库」才生成全套资料并进入正式演员库。'));
    const grid = el('div', { class: 'grid cols3' });
    for (const c of candidates) {
      const doSign = () => {
        const nameI = el('input', { type: 'text', value: c.name });
        modal({
          title: `签约入库 · ${c.name}`,
          body: el('div', {},
            el('div', { class: 'small dim', style: { marginBottom: '10px' } },
              '全链:三视图(约10min,含 VLM 自检)→ 裁正/侧身 → 3种子特写 VLM 选优 → 搬入正式演员库(自动分配 角色X_ 前缀)。'),
            el('label', { class: 'field' }, el('span', {}, '入库艺名'), nameI)),
          actions: [
            { label: '取消', kind: 'ghost', onclick: c2 => c2() },
            { label: '✍ 签约', kind: 'primary', onclick: c2 => {
              c2();
              submitJob(`/api/audition/${encodeURIComponent(c.name)}/sign`,
                { name_override: nameI.value.trim() || null });
            } },
          ],
        });
      };
      grid.append(el('div', { class: 'card' },
        el('div', { class: 'spread' },
          el('b', {}, c.name),
          el('span', { class: `chip ${c.status === '资料就绪' ? 'ok' : c.audition ? 'info' : 'warn'}` }, c.status)),
        c.audition
          ? el('img', { class: 'thumb', src: mediaUrl(c.audition), style: { marginTop: '8px' } })
          : el('div', { class: 'empty', style: { padding: '30px 0', margin: '8px 0', background: 'var(--bg)', borderRadius: '8px' } }, '试镜照待生成'),
        el('div', { class: 'small dim' }, c.positioning_cn || ''),
        el('details', { style: { marginTop: '6px' } },
          el('summary', { class: 'small dim' }, '角色 DNA'),
          el('pre', { class: 'box small' }, `face:   ${c.face_dna || '-'}\noutfit: ${c.outfit_dna || '-'}\nseed:   ${c.seed ?? '-'}`)),
        el('div', { class: 'row', style: { marginTop: '6px' } },
          el('button', { class: 'btn sm', onclick: () => submitJob(`/api/audition/${encodeURIComponent(c.name)}/reroll`, {}) }, '🎲 重掷试镜照'),
          el('button', { class: 'btn primary sm', onclick: doSign }, '✍ 签约入库'),
          el('button', {
            class: 'btn danger sm',
            onclick: () => confirmModal(`丢弃候选 ${c.name}`, '删除候选目录(不影响正式演员库)。', async () => {
              try { await api.post(`/api/audition/${encodeURIComponent(c.name)}/discard`, {}); toast('已丢弃', 'ok'); paint(); }
              catch (e) { toast(e.message, 'bad'); }
            }, '丢弃'),
          }, '🗑'))));
    }
    candBox.append(grid);
  };

  // ---------- 正式演员 ----------
  const actorBox = el('div', {});
  const paintActors = () => {
    clear(actorBox);
    actorBox.append(el('h2', {}, `👥 正式演员库(${actors.filter(a => a.complete).length}/${actors.length} 可开拍)`));
    const grid = el('div', { class: 'grid cols3' });
    for (const a of actors) {
      const run = (char, op, text) => confirmModal(`${op === 'buildrefs' ? '补参考图' : '转台参考集'} · ${char}`,
        text, () => submitJob(`/api/pool/${encodeURIComponent(char)}/run`, { op }));
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
    actorBox.append(grid);
  };

  const paint = async () => {
    try {
      [actors, candidates] = await Promise.all([
        api.get('/api/pool').then(r => r.actors),
        api.get('/api/audition').then(r => r.candidates)]);
    } catch { }
    paintCandidates();
    paintActors();
  };

  root.append(
    el('h1', {}, '演员库'),
    el('div', { class: 'spread' },
      el('p', { class: 'page-sub', style: { margin: 0 } },
        '正式演员 + 候选试镜区;签约新演员:一句话要求 → agent 优化人设 → 试镜照 → 全套资料入库。'),
      el('div', { class: 'row' },
        el('button', { class: 'btn primary', onclick: signLead }, '＋ 签约主演'),
        el('button', { class: 'btn', onclick: signExtras }, '＋ 签约群演(批量)'))),
    candBox, actorBox);

  paintCandidates();
  paintActors();

  const off = bus.on('job', (j) => {
    if (j.type && j.type.startsWith('audition') && ['done', 'failed'].includes(j.status)) paint();
  });
  return { dispose: off, refresh: paint };
}
