// actions.js —— 面板间共享的动作 modal:重拍 / 重生成
import { api, mediaUrl } from '../api.js';
import { el, toast, modal } from '../ui.js';

export function retakeModal(name, c, refresh, prefill = '') {
  const ta = el('textarea', { placeholder: '例:翻转价签动作要明确,结尾不要看镜头(留空=仅换 seed 重拍)' }, prefill);
  modal({
    title: `重拍 ${c.case}`,
    body: el('div', {},
      el('div', { class: 'small dim', style: { marginBottom: '8px' } },
        '审片建议会经 LLM 外科手术式改写该镜 dd(过 lint 闸),DNA/音乐逐字保留,换新 seed;重拍后旧审片作废需复审。'),
      ta),
    actions: [
      { label: '取消', kind: 'ghost', onclick: c2 => c2() },
      { label: '🎬 重拍', kind: 'primary', onclick: (c2) => {
        c2();
        api.post(`/api/projects/${name}/run`, { op: 'retake', case: c.case, advice: ta.value.trim() })
          .then(r => { toast(`🚀 已提交:${r.job.title}`, 'ok'); refresh(); })
          .catch(e => toast(`提交失败:${e.message}`, 'bad', 6000));
      } },
    ],
  });
}

export function regenModal(name, c, refresh) {
  const steps = el('input', { type: 'number', value: '14', min: '8', max: '30' });
  const seed = el('input', { type: 'number', placeholder: '留空=沿用该镜 seed' });
  modal({
    title: `重生成 ${c.case}(母版档,~10分钟/镜)`,
    body: el('div', {},
      el('div', { class: 'small dim', style: { marginBottom: '10px' } },
        'res_multistep 本地重生成链:对复杂动作/顽固镜通过率远高于 turbo 草稿;产出在 regen/ 目录,可入母版链。'),
      el('label', { class: 'field' }, el('span', {}, 'steps'), steps),
      el('label', { class: 'field' }, el('span', {}, 'seed(可选)'), seed)),
    actions: [
      { label: '取消', kind: 'ghost', onclick: c2 => c2() },
      { label: '启动重生成', kind: 'primary', onclick: (c2) => {
        c2();
        api.post(`/api/projects/${name}/run`, { op: 'regen', case: c.case, steps: +steps.value, seed: seed.value ? +seed.value : null })
          .then(r => { toast(`🚀 已提交:${r.job.title}(挂机档,可切走)`, 'ok'); refresh(); })
          .catch(e => toast(`提交失败:${e.message}`, 'bad', 6000));
      } },
    ],
  });
}

export function videoModal(title, mp4) {
  modal({ title, wide: true, body: el('video', { src: mediaUrl(mp4), controls: '', autoplay: '' }) });
}
