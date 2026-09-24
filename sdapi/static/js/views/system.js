// system.js —— 系统页:服务配置 + doctor 预检 + 架构速览
import { api } from '../api.js';
import * as bus from '../bus.js';
import { el, statusChip, logBox } from '../ui.js';

export default async function render(root) {
  let cfg = null;
  try { cfg = await api.get('/api/config'); } catch { }

  const doctorOut = el('div', {});
  const runDoctor = async (llm) => {
    try {
      const r = await api.post('/api/doctor', { llm });
      doctorOut.innerHTML = '';
      doctorOut.append(el('div', { class: 'row', style: { margin: '8px 0' } },
        statusChip('running'), el('b', {}, r.job.title), el('span', { class: 'faint small' }, r.job.id)));
    } catch (e) { doctorOut.append(el('div', { class: 'small' }, e.message)); }
  };

  const off = bus.on('job', async (j) => {
    if (j.type !== 'doctor' || !['done', 'failed'].includes(j.status)) return;
    try {
      const full = await api.get(`/api/jobs/${j.id}`);
      doctorOut.innerHTML = '';
      doctorOut.append(
        el('div', { class: 'row', style: { margin: '8px 0' } },
          statusChip(j.status), el('b', {}, j.title)),
        logBox(full.log.join('\n') || '(无输出)', '340px'));
    } catch { }
  });

  const rows = cfg ? [
    ['项目目录', cfg.projects], ['runtime(docker 边界)', cfg.runtime],
    ['演员库工坊', cfg.workshop], ['桌面交付', cfg.desktop],
    ['文本/快速模型', `${cfg.models.text} / ${cfg.models.fast}`], ['视觉审片模型', cfg.models.vision],
    ['镜头规格', `${cfg.video.w}×${cfg.video.h} · ${cfg.video.seconds}s/镜 · 121帧@24fps`],
    ['ComfyUI(母版/重生成)', cfg.comfyui], ['本服务', `${cfg.host}:${cfg.port}(单 worker)`],
  ] : [];

  root.append(
    el('h1', {}, '系统'),
    el('p', { class: 'page-sub' }, '单进程 FastAPI + 进程内任务调度(单 GPU 工作站架构,参照 showvi / ComfyUI 模式)。'),
    el('div', { class: 'card' },
      el('h3', {}, '🩺 环境预检(doctor)'),
      el('div', { class: 'row' },
        el('button', { class: 'btn sm', onclick: () => runDoctor(false) }, '快速预检'),
        el('button', { class: 'btn ghost sm', onclick: () => runDoctor(true) }, '含 LLM 实测'),
        el('span', { class: 'small dim' }, 'ffmpeg/磁盘/内存/GPU空闲/docker/Sol-H3/演员库/智谱key/ComfyUI')),
      doctorOut),
    cfg ? el('div', { class: 'card' },
      el('h3', {}, '⚙️ 服务配置'),
      el('table', { class: 'tbl' },
        el('tbody', {}, ...rows.map(([k, v]) => el('tr', {},
          el('td', { class: 'dim', style: { width: '180px' } }, k),
          el('td', { class: 'mono small' }, String(v))))))) : null,
    el('div', { class: 'card' },
      el('h3', {}, '🧱 架构速览'),
      el('pre', { class: 'box', style: { margin: 0 } },
`浏览器(原生 ES Module,无构建)
   │ REST + WebSocket(任务/日志/审批事件)
   ▼
sdapi :8620  FastAPI 单 worker
   ├─ JobManager   按项目串行 + 全局 GPU 锁 + print捕获 + gen日志tail
   ├─ AgentService 7 agent 门面(cast…deliver) + 分步流水线编排
   └─ Media        白名单根 + HTTP Range
   ▼                        ▼
Sol-H3 infer(docker)     ComfyUI :8189(母版/重生成)
智谱 GLM(编剧/评审/审片 VLM)`)));
  return { dispose: off };
}
