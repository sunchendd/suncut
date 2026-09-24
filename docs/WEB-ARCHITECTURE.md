# 短剧流水线 · 网页工作台架构设计(sdapi)

> 版本: v1.0 (2026-09-24)
> 代码: `shortdrama/sdapi/`(本目录为设计文档;实现见 sdapi/)
> 定位: 把纯后台 CLI 流水线(python3 -m sd)升级为**网页可控的微服务工作台**,
> 使用者可代入七个 agent 角色把控质量与成品,同时保留全自动档。

---

## 1. 需求与约束

| 需求(来自设计文档 v1.0) | 工作台翻译 |
|---|---|
| 人工只保留审片否决权与后期配音位 | 审片台的人工通过/否决并重拍;分步流水线的阶段放行门 |
| 断点续跑,阶段产物存在即跳过 | 任务与产物全部落盘,服务重启不丢进度,网页随时重进 |
| 全自动按时效选档(草稿/母版/终极) | 三档按钮:开拍(produce)、母版超分(master)、14步重生成(regen) |
| 单镜≤2人、DNA 不许 LLM 改写 | dd 编辑走 lint 闸 + `_rebuild_prompt` 外科手术,DNA/音乐逐字保留 |

**环境约束(决定架构)**: 单机 GPU 工作站(GB10)、Sol-H3 infer 走 docker 且只挂载
`~/sol-h3-spark-runtime`、ComfyUI 8189 与 infer **互斥占卡**、`state.json` 无锁读改写、
sd/ 全部 print 输出、单人使用。

## 2. 开源参考结论(为什么是这个架构)

调研了 LangGraph Studio / Dify / Flowise / n8n / AgentScope 2.0 / ComfyUI / showvi:

- **showvi**(MIT,与本流水线几乎同构的 7-agent 视频系统):FastAPI **单 worker** +
  进程内 asyncio 调度器(`asyncio.to_thread` 跑同步引擎)+ 原生 ES Module 无构建前端 +
  WS 全量快照/增量推送 + checkpoint 落盘恢复。它的 server.py 注释明确写了
  "依赖进程内状态与 WebSocket 连接管理,不支持多 worker" —— 我们同款约束。
- **ComfyUI**:单进程 aiohttp + 静态前端;`/prompt` 入队返回 id、`/ws` 推
  executing/progress 事件、`/view` 带白名单的媒体服务、队列可取消 —— 我们的
  Job/Media 设计直接对齐这套已验证的协议形态。
- **Dify(celery+redis+pg)** 是多租户云服务形态;单机单用户引入两个常驻中间件只有
  成本没有收益。**可靠性不靠消息队列,靠磁盘 checkpoint**(sd 的产物文件天然就是)。

**结论**: 单进程 FastAPI(强制 workers=1)+ 进程内 JobManager + WebSocket 进度/审批推送 +
无构建 ES Module 前端。这也是 ComfyUI 的演进路径启示:API/WS 协议设计干净,将来前端可
整体替换为预构建 React 而后端不动。

## 3. 微服务划分(逻辑四服务,物理一进程 + 两个既有执行器)

```
浏览器(原生 ES Module,无构建,零 Node 工具链)
   │  REST(提交/查询/审批) + WebSocket(任务状态/日志/心跳)
   ▼
┌─ sdapi :8620 ─── FastAPI 单 worker ──────────────────────────┐
│  Gateway 层   server.py   路由/静态/媒体网关(Range,白名单根) │
│  任务服务     jobs.py     JobManager:按项目串行+全局GPU锁     │
│                           +PrintHub(print→任务日志)+日志tail  │
│  Agent 服务   agents.py   7 agent 门面 + 分步流水线编排(审批门)│
│  读模型       detail.py   散落 JSON → 一份前端可渲染的详情      │
└───────────────────────────────────────────────────────────────┘
   ▼(进程内调用,零改动复用)        ▼(HTTP)              ▼(云)
 sd/ 领域包(7 agent 实现)      ComfyUI :8189          智谱 GLM
   ▼                            (母版SPAN/14步regen)   (编剧/评审/审片VLM)
 Sol-H3 infer(docker,经 director 适配器)
```

- **为什么不是多个 OS 进程**: 三个执行器(infer 容器、ComfyUI、LLM 云端)本来就是独立
  服务;编排队层再拆多进程只会把"state.json 无锁"的坑放大成分布式一致性问题和 GPU 双占。
  单进程内的"逻辑微服务"边界(文件级分离、无共享可变状态)保留了拆分的可能。
- **升级路径**: 多机时把 JobManager 换成 Redis 队列 + worker 进程,REST/WS 协议不变;
  前端可换预构建 React,`/api/*` 不变。

## 4. 任务模型(核心)

```
Job: id/type/title/project/status/meta/log/result
status: queued → running → (awaiting ⇄ running) → done | failed | cancelled
```

**并发规则**(每一条都对应 sd 代码的实测坑):

| 规则 | 原因 |
|---|---|
| 同一项目同时只允许 1 个任务(其余 409) | `state.json` 读-改-整写无锁,并发互相覆盖丢 takes |
| GPU 类 op 共用一把全局锁串行 | ComfyUI 与 infer 互斥占卡(设计文档 §8);D2/D4 的目录竞争 |
| `SystemExit` 按 BaseException 捕获归类 | `producer.produce` 用 raise SystemExit 报错/成功退出 |
| 取消只在审批门/阶段间隙生效 | docker infer 中途强杀会留脏目录,断点续跑产物按设计不可中断复用 |

**进度捕获三层**(sd 无结构化日志):
1. `PrintHub` 接管 `sys.stdout`,按**发起线程**分发到 Job 日志(比 redirect_stdout
   进程全局替换安全,多任务并发不串流);
2. `GenLogTailer` 轮询 runtime 下 `gen-*.log` 增量(infer 容器 stdout 落盘处);
3. `metrics.json`/`state.json` 落盘时间戳作为阶段级进度(读模型直接聚合)。

**审批门(分步流水线 op_pipeline)**: cast→materials→script→storyboard 每阶段完成后
`job.await_gate()` 挂起(status=awaiting,WS 推 note+产物提示),网页「放行继续/取消」
REST 回传;**审片后必停一档**(列出未过镜头+重拍建议),这是网页工作台的核心质控位
—— 等价于 LangGraph `interrupt()/resume` 的本地化实现。全自动档 `produce` 不设门。

## 5. API 一览(REST + WS)

| 方法/路径 | 用途 |
|---|---|
| GET `/api/overview` | 仪表盘:项目列表+状态摘要+近期任务 |
| POST `/api/projects` | 新建(name/brief/shots) |
| GET `/api/projects/{n}` | **读模型聚合**:brief/stages/cast/materials/script/storyboard/cases(每镜 join 了 dd/video/review/takes/抽帧)/picks/deliverables/gen_logs/metrics/busy |
| POST `/api/projects/{n}/run` | 提交任务:op∈{cast..deliver,master,retake,regen,produce,pipeline}+force/mode/case/advice/steps/seed |
| POST `/api/projects/{n}/dd` | dd 外科手术编辑(lint 闸,422 返回命中规则) |
| POST `/api/projects/{n}/brief` | 改梗概(提示下游需 force 重跑) |
| POST `/api/projects/{n}/review/human` | 人工通过/否决标记(否决引导重拍) |
| GET `/api/pool`、POST `/api/pool/{char}/run` | 演员库浏览、buildrefs/turntable |
| GET `/api/jobs[?project=]`、GET `/api/jobs/{id}` | 任务列表/详情(含日志 tail) |
| POST `/api/jobs/{id}/resume|cancel` | 审批门放行/取消 |
| POST `/api/doctor` | 环境预检(任务化,含可选 LLM 实测) |
| GET `/api/media?path=&download=` | 白名单根(projects/runtime/工坊/桌面)+ HTTP Range 视频 |
| GET `/api/projects/{n}/log/{which}` | 查看 gen-*.log(防穿越) |
| WS `/api/ws` | hello 全量 → `job`(状态/meta)/`log`(增量行)/`ping` 心跳 25s |

## 6. 安全边界

- 默认只听 `127.0.0.1`;局域网访问显式 `SDAPI_HOST=0.0.0.0`(工作站内网,无鉴权,
  文档明示风险自负)。
- 媒体服务只放行 `MEDIA_ROOTS` 四个根 + 扩展名白名单,`.resolve()` 防符号链接逃逸;
  `/etc/passwd` 实测 403。
- 写操作全部走 sd 领域代码既有路径(原子性/tmp+rename 由 dd 编辑自行保证);
  服务层不引入第二套写 state 的代码路径。
- API 不回显智谱 key,只显示 key 文件路径与模型名。

## 7. 已知边界(诚实清单)

- 任务表在内存:服务重启后任务历史清空(产物/断点不受影响);`/api/jobs` 页有提示。
- infer 中途不可强杀(设计使然:残留目录自动避让+缺镜自愈);取消只对分步流水线有效。
- `qwenimage._gen_one` 子进程输出被 capture,补图任务只有阶段级输出,无逐张进度。
- reviewer 自带 3 线程 VLM 并发;多项目同时审片会对 GLM-4.5v 放大 3×N 并发,注意限流。
- 桌面交付物(~/桌面 副本)经 MEDIA_ROOTS 可看,但 deliver 的写外溢仍由 sd 控制台语义决定。

## 8. 部署与运维

```bash
# 一次性
python3 -m venv ~/venvs/sdapi
~/venvs/sdapi/bin/pip install fastapi 'uvicorn[standard]'

# 启动(默认 127.0.0.1:8620)
shortdrama/scripts/sdapi-serve.sh
# 局域网: SDAPI_HOST=0.0.0.0 SDAPI_PORT=8620 scripts/sdapi-serve.sh
```

服务日志 `/tmp/sdapi.log`;强制 **workers=1**(进程内任务调度语义,勿加)。
