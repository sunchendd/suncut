// api.js —— REST 客户端:统一错误吐 detail
async function req(method, url, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(url, opt);
  let data = null;
  try { data = await r.json(); } catch { /* 非 JSON */ }
  if (!r.ok) {
    const e = new Error((data && (data.detail || data.error)) || `HTTP ${r.status}`);
    e.status = r.status; e.data = data;
    throw e;
  }
  return data;
}

export const api = {
  get: (u) => req('GET', u),
  post: (u, b = {}) => req('POST', u, b),
  del: (u) => req('DELETE', u),
  put: (u, b = {}) => req('PUT', u, b),
};

export const mediaUrl = (path, download = false) =>
  `/api/media?path=${encodeURIComponent(path)}${download ? '&download=1' : ''}`;

export const fmtBytes = (n) => {
  if (n == null) return '-';
  const u = ['B', 'K', 'M', 'G'];
  let i = 0; while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return n.toFixed(n < 10 && i > 0 ? 1 : 0) + u[i];
};

export const fmtDur = (s) => {
  if (s == null) return '-';
  s = Math.round(s);
  if (s < 60) return s + 's';
  const m = Math.floor(s / 60), h = Math.floor(m / 60);
  return h ? `${h}h${m % 60}m` : `${m}m${s % 60}s`;
};
