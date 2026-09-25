// dubbing.js —— ⑦ 配音师 agent 面板:音色分配 / VO 时间表 / 预览试听 / BGM 替换
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
        '台词/旁白 → edge-tts 分角色配音(按角色气质自动选音色)→ 全片 VO 音轨;交付时侧链压制混入(人声处音乐自动让路)。把 bgm.mp3 传进来可全片替换配乐。')),
    el('div', { class: 'row' },
      el('button', { class: 'btn primary sm', disabled: !!d.busy, onclick: uploadBgm }, '🎵 上传 BGM'),
      bgmBtn(),
      el('button', { class: 'btn sm', disabled: !!d.busy,
        onclick: () => run('dub', { force: true }, '重新配音(重读剧本台词/旁白、重分配音色、重混预览)。') }, '↻ 重新配音'))));

  // ---------- BGM ----------
  function bgmBtn() {
    const has = !!(dub.bgm_override);
    return has
      ? el('button', { class: 'btn danger sm', disabled: !!d.busy, onclick: async () => {
          try { await api.del(`/api/projects/${name}/bgm`); toast('已删除 BGM,恢复视频原声', 'ok'); refresh(); }
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
          '替换 Sol-H3 生成音轨:循环铺满全片、响度统一、人声出现处自动压低(侧链)。删除即恢复视频原声。不传则用视频自带配乐(95BPM 音乐块)。'),
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
  if (dub.bgm_override) box.append(el('div', { class: 'small dim' },
    '🎵 BGM 替换已启用:', dub.bgm_override));
  return box;
}
