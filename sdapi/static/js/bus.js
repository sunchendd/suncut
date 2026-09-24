// bus.js —— WebSocket 客户端:自动重连(指数退避到 30s),事件订阅
const handlers = new Map();
let ws = null;
let retry = 0;
let statusFn = null;

export function on(type, fn) {
  if (!handlers.has(type)) handlers.set(type, new Set());
  handlers.get(type).add(fn);
  return () => handlers.get(type)?.delete(fn);
}

export function onStatus(fn) { statusFn = fn; }

function dispatch(msg) {
  const set = handlers.get(msg.type);
  if (set) for (const fn of set) fn(msg);
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/api/ws`);
  ws.onopen = () => {
    const wasDown = retry > 0;
    retry = 0; statusFn?.(true);
    if (wasDown) dispatch({ type: 'resync' });   // 断线重连后通知各视图重拉状态
  };
  ws.onmessage = (ev) => {
    try { dispatch(JSON.parse(ev.data)); } catch { /* 忽略坏帧 */ }
  };
  ws.onclose = () => {
    statusFn?.(false);
    const wait = Math.min(30000, 1000 * 2 ** retry++);
    setTimeout(connect, wait);
  };
  ws.onerror = () => ws.close();
}

export function start() { connect(); }
export function send(msg) {
  if (ws?.readyState === 1) ws.send(typeof msg === 'string' ? msg : JSON.stringify(msg));
}
