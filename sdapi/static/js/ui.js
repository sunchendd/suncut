// ui.js —— DOM/弹窗/toast 等界面工具
export function el(tag, props = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === 'class') n.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(n.style, v);
    else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
    else if (k === 'href') n.setAttribute('href', v);
    else if (k === 'dataset') Object.assign(n.dataset, v);
    else if (v !== undefined && v !== null && v !== false) n.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat(9)) {
    if (c === null || c === undefined || c === false) continue;
    n.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return n;
}

export function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

export function toast(msg, kind = 'info', ms = 3600) {
  const box = document.getElementById('toasts');
  const t = el('div', { class: `toast ${kind}` }, msg);
  box.append(t);
  setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity .3s'; setTimeout(() => t.remove(), 350); }, ms);
}

export function modal({ title, body, actions = [], wide = false }) {
  const root = document.getElementById('modal-root');
  const close = () => back.remove();
  const back = el('div', { class: 'modal-back', onclick: (e) => { if (e.target === back) close(); } },
    el('div', { class: 'modal', style: wide ? { width: 'min(980px, 96vw)' } : {} },
      el('div', { class: 'modal-head' }, el('h3', {}, title), el('span', { class: 'x', onclick: close }, '×')),
      el('div', { class: 'modal-body' }, body),
      actions.length ? el('div', { class: 'modal-foot' },
        ...actions.map(a => el('button', {
          class: `btn ${a.kind || ''}`, onclick: () => a.onclick?.(close),
        }, a.label))) : null));
  root.append(back);
  return { close, back };
}

export function scoreBars(scores) {
  if (!scores) return el('span', { class: 'faint small' }, '暂无评分');
  const NAME = { identity: '角色一致性', action: '动作完成度', composition: '构图美感' };
  return el('div', {},
    Object.entries(scores).filter(([k]) => NAME[k]).map(([k, v]) => {
      const pct = Math.max(0, Math.min(10, Number(v) || 0)) * 10;
      const cls = v >= 8 ? '' : v >= 7 ? 'mid' : 'low';
      return el('div', { class: 'score-row' },
        el('span', { class: 'name' }, NAME[k]),
        el('div', { class: 'score-bar' }, el('div', { class: `score-fill ${cls}`, style: { width: pct + '%' } })),
        el('span', { class: 'val' }, String(v)));
    }));
}

export function statusChip(status) {
  const MAP = { running: 'info', awaiting: 'warn', queued: 'warn', done: 'ok', failed: 'bad', cancelled: '' };
  const TXT = { running: '运行中', awaiting: '待放行', queued: '排队', done: '完成', failed: '失败', cancelled: '已取消' };
  return el('span', { class: `chip ${MAP[status] || ''}` },
    el('span', { class: `status-dot ${status}` }), TXT[status] || status);
}

export function logBox(lines = [], maxH) {
  const box = el('div', { class: 'joblog' }, lines.length ? lines.join('\n') : '(暂无输出)');
  if (maxH) box.style.maxHeight = maxH;
  return box;
}

export function confirmModal(title, text, onOk, okLabel = '确认') {
  modal({
    title,
    body: el('div', {}, text),
    actions: [
      { label: '取消', kind: 'ghost', onclick: (close) => close() },
      { label: okLabel, kind: 'primary', onclick: (close) => { close(); onOk(); } },
    ],
  });
}
