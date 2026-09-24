# suncut — 本地 AI 短剧流水线 + 网页工作台

一句话故事梗概 → 可发布竖版短剧(1080×1920)的全自动本地流水线。
**七个 agent 分工**(招聘/物料/编剧/分镜/导演/审片/制片),本地 Qwen-Image-2.1 出图 +
Sol-H3(MiniMax-H3)出视频,LLM 走智谱 GLM;支持 CLI 全自动与**网页工作台人工质控**两种开拍方式。

```
浏览器工作台(可选,质控位)            CLI 全自动
        │ REST + WebSocket                 │
        ▼                                  ▼
   sdapi :8620 (FastAPI)              python3 -m sd produce
        └──────────► sd/ 七 agent 领域包(共用,零改动)◄──────────┘
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
  Sol-H3 infer(docker) ComfyUI :8189   智谱 GLM(编剧/评审/审片VLM)
  草稿视频 ~70-120s/镜   母版超分/14步重生成   token 走 Coding Plan
```

---

## 1. 环境要求与一次性安装

**机器**:DGX Spark(GB10)或同级 CUDA 环境;磁盘 ≥50G 空闲;内存 ≥40G。

**前置依赖**(本机已就绪,换机需重装):

| 依赖 | 位置/检查方式 |
|---|---|
| ffmpeg / ffprobe | `ffmpeg -version` |
| docker + Sol-H3-Spark | `~/.zcode/workspace/default/Sana/models/minimax_h3/Sol-H3-Spark/infer.py` |
| ComfyUI(母版/重生成用) | `http://127.0.0.1:8189`,不在时会自动拉起 |
| Qwen-Image-2.1 | `~/models/Qwen-Image-2.1` + `~/venvs/imagegen`(diffusers) |
| 演员库工坊 | `~/桌面/AI角色工坊/素材/<角色>/角色提示词.md` |
| 智谱 API key | `~/.zcode/v2/provider_config.json`(自动读取,换 key 免重启) |

**安装工作台服务**(独立 venv,不污染 sd 的零依赖):

```bash
python3 -m venv ~/venvs/sdapi
~/venvs/sdapi/bin/pip install fastapi 'uvicorn[standard]'
```

**开拍前体检**(两分钟,查工具/磁盘/内存/GPU/docker/演员库/key/ComfyUI):

```bash
cd ~/Desktop/suncut && python3 -m sd doctor        # 加 --llm 附带 LLM 实测
```

## 2. 启动网页工作台(推荐入口)

```bash
cd ~/Desktop/suncut
scripts/sdapi-serve.sh                 # 默认 http://127.0.0.1:8620(单 worker,勿加)
# 局域网访问(手机/平板也可开): SDAPI_HOST=0.0.0.0 scripts/sdapi-serve.sh
# 服务日志: /tmp/sdapi.log
```

## 3. 工作台使用指导

### 3.1 仪表盘 —— 建项目、选开拍模式

- **＋ 新建项目**:项目名(英文/拼音)+ **故事梗概一句话**(全片唯一人工输入)+ 镜头数(1 镜≈5秒);
- 项目卡显示七阶段进度条、审片通过率、忙碌状态;
- 两种开拍模式:
  - **🎬 全自动**:一次到底,审片不过自动重拍≤2轮,全片约 1-2 小时(4镜);
  - **🧭 分步流水线**:每个 agent 完成后**暂停等你放行**,审片后必停一档——逐段把控质量用这个。

### 3.2 项目工作台 —— 七个 agent 面板

顶部步进器点击切换面板(✓=已完成,⟳=运行中,⏸=待放行):

| 面板 | 能看什么 | 能做什么 |
|---|---|---|
| ① 招聘 | 选角卡:选角理由/服装备注/角色DNA/三视图 | ↻重新招聘;跳演员库补资料 |
| ② 物料 | 场景DNA(点光源)/音乐块(95BPM)/道具/空镜 | ↻重新生成 |
| ③ 编剧 | 标题/一句话/自评四维/镜次表/旁白 | ↻重写;下载 narration.srt(剪映用) |
| ④ 分镜 | 每镜 dd/运镜/seed/lint记录 | **✏️ 编辑 dd**(过 lint 闸,DNA 逐字保留) |
| ⑤ 导演 | 每镜视频+重拍条历史 | **🎥 重拍**(填建议)/💎 14步重生成;看 infer 日志 |
| ⑥ 审片 | 抽帧四宫格/三维分/重拍建议/条历史 | **人工通过 / ⛔ 否决并重拍**(核心质控位) |
| ⑦ 制片 | 选条表/成片/封面/制作报告/指标 | 📦 交付成片;💎 母版超分 |

**质控三板斧**:分步流水线的阶段放行门 → 审片否决(自动带建议发起重拍)→ dd 编辑(下次重拍/重生成即生效)。

### 3.3 演员库 / 任务中心 / 系统

- **演员库**:全员三视图完整度(可开拍/资料不全),`🧩 补三视图`(Qwen 补图×3种子 VLM 选优)、`🔄 转台参考集`;
- **任务中心**:全局任务表 + 实时日志,审批门的「放行/取消」也可在这里操作;
- **系统**:doctor 预检、路径/模型配置速览、架构图。

### 3.4 使用纪律(重要)

- **同一项目同时只跑一个任务**(state 无锁,防覆盖);GPU 任务全局串行(infer 与 ComfyUI 互斥占卡);
- 任务历史在内存里,**服务重启后清空**——但产物和断点状态全在磁盘,重开服务接着跑即可;
- 生成中的 infer 任务不能中途强杀(按设计走缺镜自愈),取消只在分步流水线的阶段间隙生效。

## 4. CLI 备用速查

```bash
python3 -m sd new <名字> --brief "故事梗概" --shots 4     # 建项目
python3 -m sd produce <名字>                              # 全自动开拍
python3 -m sd review <名字> --force                       # 重审片
python3 -m sd retake <名字> <名字-q2> --advice "建议"      # 单镜重拍
python3 -m sd master <名字>                               # 母版: SPAN×2 超分 1080p CRF14
python3 -m sd regen <名字> <名字-q2> --steps 14           # 终极: 14步重生成(~10min/镜)
python3 -m sd buildrefs <角色名关键字>                     # 演员补三视图
python3 -m sd turntable <角色名关键字>                     # 转台参考集
python3 -m sd metrics <名字> / status [名字] / doctor      # 指标/进度/体检
```

## 5. 三档质量阶梯(按时效选)

| 档 | 命令/入口 | 耗时/镜 | 用途 |
|---|---|---|---|
| 草稿 | produce / 工作台开拍 | ~70-120s | 全片审片看结构 |
| 母版 | master | ~80s | 1080p 快速交付 |
| 终极 | regen --steps 14 | ~10min(挂机) | 发布版/顽固镜(通过率档) |

## 6. 数据都在哪 / 如何迁移

| 数据 | 位置 |
|---|---|
| 项目(剧本/状态/成片/审片帧) | `<本目录>/projects/<名字>/`(2.4G 演示数据在旧位置,见下) |
| 生成视频真身 + prompts.jsonl | `~/sol-h3-spark-runtime/shortdrama/<名字>/`(docker 挂载边界,勿移动) |
| 交付副本(竖版/封面) | `~/桌面/` |
| 演员库 | `~/桌面/AI角色工坊/素材/` |

旧演示项目(雨夜便利店/天台纸灯/旧物市集/旧书店的雨夜)在
`~/.zcode/workspace/default/shortdrama/projects`。想在本副本里直接看到它们:

```bash
ln -s ~/.zcode/workspace/default/shortdrama/projects ~/Desktop/suncut/projects
```

(或者 `cp -r` 拷贝;两者的 state.json 里视频是绝对路径,指向 runtime,不受影响。)

## 7. 常见问题

| 现象 | 原因/处理 |
|---|---|
| 提交任务报 409「项目正在跑」 | 同项目单任务纪律;去任务中心看进行中的任务 |
| 生成任务很久没动静 | 看⑤导演面板 infer 日志,或任务中心实时日志;首镜含模型加载较慢 |
| 首次 master/regen 前几分钟无输出 | ComfyUI 自动拉起中(最长 ~5min),之后 ~80s/镜 |
| 审片分和上次不一样 | VLM 单次噪声±4,系统已双次取均值+条历史只升不降,属正常 |
| 换了智谱 key | 直接改 provider_config.json,免重启 |
| 视频进度条拖不动 | 不会发生:媒体网关带 HTTP Range;若发生在反向代理后,检查代理的 range 透传 |

## 8. 更多文档

- `docs/WEB-ARCHITECTURE.md` — 工作台架构设计(微服务划分/任务模型/API/WS 协议)
- `docs/AGENT-PANELS.md` — 七 agent 职责边界与网页功能映射
- `OPTIMIZATION.md` — 流水线 22 轮迭代全记录(C1-C22,每轮附证据)
- 设计蓝本与经验源:`~/桌面/短剧框架-设计文档.md`、`~/桌面/AI短剧全流程制作工作流.md`

## 9. 已知边界(诚实清单)

- 复杂动作是 H3 固有弱项,重拍边际递减,14 步档是当前最优解;
- 单镜≤2 人、群演=0 是硬约束(串脸风险);自动参考图角色略弱于手工参考集;
- 配音与剪映精剪仍是人工位(narration.srt 为字幕草稿);
- 工作台默认监听 127.0.0.1;`SDAPI_HOST=0.0.0.0` 开局域网前请自知无鉴权。
