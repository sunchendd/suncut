// storyboard.js —— ④ 分镜 agent 面板:prompts 行 + lint 结果 + dd 人工编辑(过lint闸)
import { api } from '../api.js';
import { el, toast, modal } from '../ui.js';

export default function render(ctx) {
  const { d, name, run, refresh } = ctx;
  const sb = d.storyboard || {};
  const box = el('div', {});

  box.append(el('div', { class: 'spread' },
    el('div', {},
      el('h2', {}, '分镜'),
      el('p', { class: 'page-sub' },
        'LLM 只写动作描述(dd),角色 DNA 与音乐块由程序逐字拼装(防跨镜换脸);lint 自动审稿:手部特写/正面说话/混乱快动作/动作>3节点/运镜多样性。')),
    el('button', { class: 'btn sm', disabled: !!d.busy,
      onclick: () => run('storyboard', { force: true }, '重新分镜(会重建 prompts.jsonl;已有视频作废需重拍)。') }, '↻ 重新分镜')));

  if (!sb.cases) { box.append(el('div', { class: 'card empty' }, '尚无分镜 —— 先跑「分镜」阶段')); return box; }

  // lint 汇总
  const lintInfo = sb.lint || {};
  const rounds = lintInfo.rounds || [];
  if (rounds.length) {
    box.append(el('div', { class: 'card' },
      el('h3', {}, 'lint 审稿记录'),
      ...rounds.map(r => el('div', { class: 'small row' },
        el('span', { class: `chip ${r.clean ? 'ok' : 'warn'}` }, `第${r.round}轮 ${r.clean ? '通过' : '有违规'}`),
        ...(r.cameras || []).map(c => el('span', { class: 'chip' }, c)))),
      el('div', { class: 'small faint' }, 'prompts: ', el('code', {}, sb.jsonl || '-'))));
  }

  const editDD = (c) => {
    const ta = el('textarea', { style: { minHeight: '150px' } }, c.dd || '');
    const err = el('div', { class: 'small', style: { color: 'var(--bad)', whiteSpace: 'pre-wrap' } });
    modal({
      title: `编辑动作描述 dd · ${c.case}`,
      body: el('div', {},
        el('div', { class: 'small dim', style: { marginBottom: '8px' } },
          '外科手术式修改:角色 DNA 与音乐块逐字保留,只替换 dd;必须过 lint 闸(动作≤3节点、禁手部特写/正面说话/混乱快动作)。空行留空提交即校验。'),
        ta, err),
      actions: [
        { label: '取消', kind: 'ghost', onclick: c2 => c2() },
        { label: '校验并保存', kind: 'primary', onclick: async c2 => {
          try {
            await api.post(`/api/projects/${name}/dd`, { case: c.case, dd: ta.value });
            c2(); toast(`dd 已更新:${c.case}(下次重拍/重生成即生效)`, 'ok'); refresh();
          } catch (e) {
            const hits = (e.data?.hits || []).map(h => `· ${h.rule}:${h.match ? '「' + h.match + '」' : ''} → ${h.fix}`).join('\n');
            err.textContent = hits ? `lint 未通过:\n${hits}` : e.message;
          } } },
      ],
    });
  };

  for (const c of d.cases.filter(x => x.dd)) {
    box.append(el('div', { class: 'card' },
      el('div', { class: 'spread' },
        el('div', { class: 'row' },
          el('span', { class: 'chip acc' }, c.case),
          el('span', { class: `chip ${c.task === 'ref2va' ? 'info' : ''}` }, c.task || '?'),
          c.camera ? el('span', { class: 'chip' }, '运镜 ' + c.camera) : null,
          el('span', { class: 'chip' }, `seed ${c.seed ?? '-'}`)),
        el('button', { class: 'btn sm', onclick: () => editDD(c) }, '✏️ 编辑 dd')),
      c.note ? el('div', { class: 'small dim' }, c.note) : null,
      el('details', { style: { marginTop: '6px' } },
        el('summary', { class: 'small dim' }, 'detailed_description(英文,LLM 手写部分)'),
        el('pre', { class: 'box small' }, c.dd)),
      c.soundscape ? el('details', {},
        el('summary', { class: 'small dim' }, '环境声'),
        el('div', { class: 'small' }, c.soundscape)) : null));
  }
  return box;
}
