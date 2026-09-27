// dubbing.js —— ⑦ 配音师 agent 面板:角色音色档案 / ADR / 制片 BGM
import { api, mediaUrl, fmtDur } from '../api.js';
import { el, toast, modal } from '../ui.js';

export default function render(ctx) {
  const { d, name, run, refresh } = ctx;
  const dub = d.dub || {};
  const script = d.script || {};
  const box = el('div', {});

  box.append(el('div', { class: 'spread' },
    el('div', {},
      el('h2', {}, '配音配乐'),
      el('p', { class: 'page-sub' },
        '台词/旁白以角色专属音色做后期 ADR；最终 BGM 只由制片统一铺设和混音。角色自定义或克隆音色必须有授权记录。')),
    el('div', { class: 'row' },
      el('button', { class: 'btn primary sm', disabled: !!d.busy, onclick: uploadBgm }, '🎵 上传 BGM'),
      el('button', { class: 'btn sm', disabled: !!d.busy, onclick: selectLibraryBgm }, '🎼 选择曲库 BGM'),
      bgmBtn(),
      el('button', { class: 'btn sm', disabled: !!d.busy,
        onclick: () => run('dub', { force: true }, '重新配音(重读剧本台词/旁白、重分配音色、重混预览)。') }, '↻ 重新配音'))));

  // ---------- BGM ----------
  function bgmBtn() {
    const has = !!d.bgm;
    return has
      ? el('button', { class: 'btn danger sm', disabled: !!d.busy, onclick: async () => {
          try { await api.del(`/api/projects/${name}/bgm`); toast('已删除项目 BGM', 'ok'); refresh(); }
          catch (e) { toast(e.message, 'bad'); }
        } }, '🗑 移除 BGM')
      : null;
  }
  function uploadBgm() {
    const fi = el('input', { type: 'file', accept: '.mp3,.wav,.flac,.m4a' });
    modal({
      title: '上传全片 BGM(可选)',
      body: el('div', {},
        el('div', { class: 'small dim', style: { marginBottom: '10px' } },
          '上传你拥有使用权的完整 BGM。它只在制片最终混音时循环铺满全片、在人声处自动让路；不再使用逐镜随机配乐。'),
        fi),
      actions: [
        { label: '取消', kind: 'ghost', onclick: c => c() },
        { label: '上传', kind: 'primary', onclick: async c => {
          const f = fi.files?.[0];
          if (!f) { toast('先选择文件', 'warn'); return; }
          try {
            const r = await fetch(`/api/projects/${name}/bgm`, {
              method: 'POST', body: f,
              headers: { 'Content-Type': f.type || 'application/octet-stream' } });
            const j = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
            c(); toast(`BGM 已上传(${j.duration}s)—— 重新配音或交付时生效`, 'ok', 6000); refresh();
          } catch (e) { toast(e.message, 'bad', 6000); }
        } },
      ],
    });
  }

  async function selectLibraryBgm() {
    try {
      const tracks = (await api.get('/api/music-library')).tracks || [];
      const approved = tracks.filter(t => t.rights?.approved);
      if (!approved.length) { toast('曲库暂无已授权曲目；请先登记 catalog.json 和素材文件', 'warn', 6000); return; }
      const choice = el('select', {});
      approved.forEach(t => choice.append(el('option', { value: t.id }, `${t.title || t.id} · ${t.bpm || '?'} BPM · ${(t.mood_tags || []).join('/')}`)));
      modal({ title: '选择已授权 BGM', body: el('div', {},
        el('p', { class: 'small dim' }, '制片会在最终交付时使用此曲并记录授权台账。'), choice), actions: [
          { label: '取消', kind: 'ghost', onclick: c => c() },
          { label: '选用', kind: 'primary', onclick: async c => {
            try { const r = await api.post(`/api/projects/${name}/bgm/library`, { track_id: choice.value }); c(); toast(`已选择 BGM：${r.bgm.title || choice.value}`, 'ok'); refresh(); }
            catch (e) { toast(e.message, 'bad'); }
          } },
        ] });
    } catch (e) { toast(e.message, 'bad'); }
  }

  if (!d.stages?.dub) {
    box.append(el('div', { class: 'card empty' },
      '尚未配音 —— 编剧完成后跑「配音配乐」阶段(edge-tts,无需 GPU)。'));
    return box;
  }

  // ---------- 音色分配 ----------
  const voiceNames = Object.entries(dub.voice_ids || {});
  if (voiceNames.length) box.append(el('div', { class: 'card' },
    el('h3', {}, '🎙 音色分配(LLM 按角色气质挑选)'),
    el('div', { class: 'row' },
      ...voiceNames.map(([label, id]) => el('span', { class: `chip ${label === dub.narrator ? 'acc' : ''}`,
        title: id }, `${label === dub.narrator ? '旁白 · ' : ''}${label}`)))));

  // ---------- VO 段落表 ----------
  const segs = dub.segments || [];
  if (!segs.length) {
    box.append(el('div', { class: 'card empty' }, '剧本无台词无旁白 —— 空音轨(纯环境声/配乐直出)'));
  } else {
    const tbl = el('table', { class: 'tbl' },
      el('thead', {}, el('tr', {},
        el('th', {}, '#'), el('th', {}, '镜'), el('th', {}, '说话人'), el('th', {}, '音色'),
        el('th', {}, '内容'), el('th', {}, '起点'), el('th', {}, '时长'), el('th', {}, '试听'))),
      el('tbody', {}, ...segs.map((s, i) => el('tr', {},
        el('td', {}, String(i + 1)),
        el('td', {}, el('span', { class: 'chip' }, s.shot)),
        el('td', {}, s.who),
        el('td', {}, el('span', { class: 'small' }, s.voice)),
        el('td', { style: { maxWidth: '220px' } }, s.text),
        el('td', {}, s.t_start + 's'),
        el('td', {}, `${s.dur}s${s.rate_boost ? `(+${s.rate_boost}%)` : ''}`),
        el('td', {}, s.file
          ? el('button', { class: 'btn ghost sm', onclick: () => new Audio(mediaUrl(s.file)).play() }, '▶')
          : '-')))));
    box.append(el('div', { class: 'card', style: { padding: '6px 10px' } },
      el('h3', { style: { padding: '6px 4px 0' } }, `🎧 VO 时间表(${segs.length} 段)`),
      el('div', { class: 'scroll-x' }, tbl)));
  }

  // ---------- 预览混音 ----------
  if (dub.preview) {
    box.append(el('div', { class: 'card accent' },
      el('div', { class: 'spread' },
        el('h3', {}, '🎬 配音预览(当前最佳条 × 侧链混音)'),
        el('span', { class: 'small faint' }, '交付时会按当时的选条重新混音,重拍不影响')),
      el('video', { src: mediaUrl(dub.preview), controls: '', preload: 'metadata',
        style: { width: '100%', maxHeight: '300px' } })));
  } else if (dub.preview_error) {
    box.append(el('div', { class: 'card empty' }, '预览未生成(尚无视频产物):', dub.preview_error));
  }
  if (d.bgm) box.append(el('div', { class: 'small dim' },
    `🎵 制片 BGM：${d.bgm.title || d.bgm.file}（${d.bgm.source === 'library' ? '已授权曲库' : '项目上传'}）`));
  return box;
}
