# 八个 Agent 的职责边界与网页功能抽象

> 版本: v2.0 (2026-09-25,D 轮: 手动选角/服化道+资产库/台词/配音师/横竖屏/字幕)
> 回答两个问题:① 每个 agent 的**责任与义务**是什么;② 由此抽象出工作台需要哪些网页功能。
> 每个面板 = 看(agent 产物)+ 控(人工介入点)+ 重(force 重跑/定向操作)。

## 0. 总原则

- **人设代入**: 工作台把每个 agent 呈现为一个"工位面板",使用者可以在任一工位
  接管该角色的人工位(审阅/修改/否决/重跑),其余交给自动化。
- **质量三闸**: lint 闸(分镜/重拍改写)→ 审片闸(VLM 三维分+人工否决)→
  交付闸(分步流水线的最终放行)。网页功能围绕这三闸展开。
- **改动永远走领域规则**: 网页编辑 dd 必须过 lint 并外科手术保留 DNA;
  否决的动作是"带 advice 的重拍"而不是绕过审片直接交付。

## 1. 招聘 casting —— 选角与演员资料包

| | |
|---|---|
| **责任** | 从 brief + 本地演员库为故事选定 1-2 名演员;产出 cast.json(选角理由/服装备注/角色 DNA/三视图 refs) |
| **义务** | 单镜≤2 人硬约束;资料包缺三视图时调 Qwen 补图×3 种子 + VLM 对照选优;不重复选同一演员 |
| **上游** | brief.txt | **下游**: 物料/编剧/分镜(角色 DNA 被逐字拼装) |

**网页功能(① 招聘面板 + 演员库页)**:
- 演员卡片: story_role、选角理由、服装备注、face/outfit DNA(折叠)、三视图图片;
- **`🖐 手动选角`**(演员卡勾选 1-2 人 + 角色名;资料不全也可选,提交后自动补三视图)与
  `🤖 让 agent 重新选(force)` 并列 —— 手动/智能双入口,数据形状完全一致;
- 选角卡带「🖐 手动」徽标(reason=人工指定);
- 演员库页: 全员网格、三视图完整度徽章(可开拍/资料不全)、角色 DNA 查看、
  `补三视图 buildrefs` / `转台参考集 turntable` 按钮(全局 GPU 任务);
- brief 编辑入口(全片唯一人工输入的修改位)。

## 2. 服化道 materials —— 场景 DNA / 音乐块 / 道具(资产库联动)

| | |
|---|---|
| **责任** | 产 scenes[](中文名+场景 DNA 英文 + 点光源中文说明 + 道具)、b_roll 空镜、全片统一 95BPM 音乐块、风格注记;新产出自动归档资产库 |
| **义务** | DNA 必含点光源关键词(程序校验,违者 raise);音乐块逐字复用到每镜 prompt;项目预选(assets.json)的场地 DNA **逐字锁定**(不经 LLM 改写),预选道具列为必用 |
| **上游** | brief + cast | **下游**: 编剧(场景引用)/分镜(DNA 拼装) |

**网页功能(② 服化道面板 + 资产库页)**:
- 场景卡片墙: 场景中文名、dna_en 全文、点光源徽章、**「库锁定」徽章**(来自预选)、道具 chips;
- 音乐块/风格注记专卡(强调"逐字复用、跨镜一致"的语义);
- 空镜 B-Roll 列表(后续走 t2va 的预告);
- **`📦 预选资产`**(弹窗勾选场地≤4/道具≤6,保存进 assets.json,下次生成生效);
- 本轮自动归档清单(新场景/新道具 chips);
- `↻ 重新生成(force)`(锁定项保持);
- **资产库页(#/assets)**: 场地/道具两组卡片,新增/编辑/删除;来源项目标注。

## 3. 编剧 screenwriter —— 剧本、台词与旁白

| | |
|---|---|
| **责任** | 产 script.json(title/logline/镜次表 shot_en+action_en+emotion_cn+**dialogue_cn 台词**+narration_cn/结尾记忆点)+ subtitles/<名>.srt 字幕(台词+旁白合并) |
| **义务** | 自评-修订闭环(flash 四维 hook/arc/narration(台词与旁白)/visual,任一<7 重写,≤2 轮);硬约束内置:5.04s/镜、动作≤3 节点、**台词每镜≤2 句每句≤18 字(画外音呈现,画面拍背影/侧脸,不对口型)**、台词+旁白合计≤25 字、旁白≤25 字、禁手部特写/正面说话 |
| **上游** | brief+cast+materials | **下游**: 分镜(dd 的创作源头)、配音师(台词/旁白即配音稿) |

**网页功能(③ 编剧面板)**:
- 剧本头卡: 标题/一句话/结尾记忆点 + 自评四维分数条(达标线 7);
- 镜次表: 场景/出场/情绪/**台词/旁白合并列**(台词带角色名 chip)/画面与动作(可展开 shot_en+action_en 全文);
- `⬇ 旁白字幕 SRT` 下载(剪映导入位);
- `↻ 重写剧本(force)`。

## 4. 分镜 storyboard —— prompts 组装与 lint 审稿

| | |
|---|---|
| **责任** | LLM 只写每镜 dd(动作描述)与 overall_soundscape;**程序逐字拼装** subject_definitions(DNA)/音乐块 → prompts.jsonl(ref2va 有人物 / t2va 空镜、case_id、seed、references 三视图复制进 runtime) |
| **义务** | lint 闸: 手部特写/正面说话/混乱快动作/动作>3 节点/运镜多样性,违规带原因让 LLM 重写(≤2 轮);安全短语程序化补齐 |
| **上游** | script+materials+cast | **下游**: 导演(唯一输入 prompts.jsonl) |

**网页功能(④ 分镜面板)**:
- 每镜卡: case/task 徽章/运镜类型/seed/note(中文摘要)/dd 与环境声折叠展示;
- lint 审稿记录(轮次/通过与否/运镜多样性清单);
- **`✏️ 编辑 dd`(人工介入核心)**: modal 编辑 → 服务端 lint 闸(422 返回命中规则与修法)
  → `_rebuild_prompt` 外科手术保留 DNA/音乐 → 原子写回 prompts.jsonl(下次重拍/重生成生效);
- `↻ 重新分镜(force)`。

## 5. 导演 director —— 视频生成执行

| | |
|---|---|
| **责任** | 按 task 分批调 Sol-H3 infer(ref2va/t2va 各自的 paths);缺镜自动重跑×2;已完成镜头跨批复用;retake=换 seed+建议改写 dd(lint 闸)+单镜批;regen=14 步本地重生成链(ComfyUI) |
| **义务** | 参考图/JSONL 必须在 runtime 挂载边界内;输出目录永不预建、残留避让;重拍条追加 takes 且作废旧审片 |
| **上游** | prompts.jsonl | **下游**: 审片(视频+抽帧) |

**网页功能(⑤ 导演面板)**:
- 每镜卡: 视频播放器(媒体网关 Range 支持)、seed/task、**重拍条历史表**(seed/依据/三维分/播放);
- `🎥 重拍` modal: advice 文本域(预填审片建议;留空=仅换 seed);
- `💎 重生成` modal: steps/seed(挂机档说明);
- `▶ 补拍缺镜`(增量)与 `↻ 全片重拍(force)`;
- infer 日志列表(gen-*.log 点击弹层查看,tailer 实时进任务日志)。

## 6. 审片 reviewer —— 质量裁判(人工否决权所在)

| | |
|---|---|
| **责任** | 逐镜: ffprobe 技术核验(时长±0.5s/音轨)→ 抽 3 帧+contact sheet → 审片 VLM(默认 glm-5.3-flash,SD_VISION_MODEL 可换) **双次评审取均值** → 三维分(角色一致性/动作完成度/构图)≥7 判过 → 未过产中文重拍建议;分数回写条历史只升不降 |
| **义务** | pass 由程序按分数计算(不信 VLM 自报布尔);3 并发控制 VLM 用量;视频集变化自动作废旧审片 |
| **上游** | generate/takes + refs + dd | **下游**: 制片(选片依据) |

**网页功能(⑥ 审片面板 = 质控核心)**:
- 总览: `x/y 过片` 徽章 + `↻ 重新审片(force)`;
- 每镜卡: 抽帧四宫格(f0/f1/f2/sheet)、视频播放、时长/音轨技术徽章、
  **三维分条**、verdict 徽章、重拍建议(橙字)、条历史分数表(只升不降);
- **`人工通过` / `⛔ 否决并重拍`**(human.json 落盘;否决即弹重拍 modal 预填建议);
- 分步流水线的**审片门**: 任务挂起在此,逐镜处置后「放行继续」才交付。

## 7. 配音师 dubbing —— 台词/旁白配音与配乐(新增)

| | |
|---|---|
| **责任** | 台词/旁白 → edge-tts 分角色配音(音色由 LLM 按角色气质从 6 条中文音色池挑选)→ 全片 VO 音轨(vo_full.wav,时间轴与字幕逐槽对齐)+ 试听预览(当前最佳条×侧链混音) |
| **义务** | 每段装不下时间槽自动提速重合成(≤+50%);产出只落 audio/(不碰视频),交付时按最新选条重混 —— **重拍换条不失效**;音频床响度统一 -17 LUFS、人声 -13 LUFS 侧链压制 |
| **上游** | script(台词/旁白)+cast(音色气质) | **下游**: 制片(交付混音) |

**网页功能(⑦ 配音师面板)**:
- 音色分配卡(角色→音色,旁白单列);
- VO 时间表(镜/说话人/音色/内容/起点/时长/逐段 ▶ 试听);
- 配音预览视频(边看边听,标注「交付时按选条重混」);
- **`🎵 上传 BGM`**(mp3/wav/flac/m4a;循环铺底+响度统一+人声让路;`🗑 移除 BGM` 恢复视频原声);
- `↻ 重新配音(force)`。

## 8. 制片 producer —— 编排交付与复盘

| | |
|---|---|
| **责任** | 全流程编排(produce: 选角→服化道→编剧→分镜→开拍→审片[重拍≤2轮]→配音→交付);deliver=按剧本顺序选每镜历史最佳条(有全≥7 条优先)拼接→(配音产物侧链混入)→**按项目设置横/竖屏+分辨率**出片→PIL 封面+制作报告,deliver/ 目录+桌面副本;master=ComfyUI SPAN×2 超分→同设置 CRF14;metrics 汇总 |
| **义务** | 配音失败不阻塞交付(原声直出);封面/报告失败不阻塞交付;三档质量阶梯按时效选档;交付物路径可追溯;**烧字幕选项**(subtitles/<名>.srt,libass+Noto Sans CJK,横竖屏均可) |
| **上游** | 全部阶段 | **下游**: 桌面/发布 |

**网页功能(⑧ 制片面板 + 仪表盘/任务中心)**:
- `📝 自动字幕` 勾选 + `📦 交付成片(force 重选)` 与 `💎 母版超分`(横竖屏/分辨率跟随项目设置,面板副标题实时显示);
- 交付选条表(每镜选中的是哪一条、判定);
- 交付物墙: 成片播放器(横/竖版)+下载、封面图、制作报告/字幕文档查看下载;
- 制作指标(metrics.txt 汇总: 各阶段耗时/秒每镜/过片率);
- 仪表盘: 项目卡(八阶段进度条/审片通过率/忙碌态)+ 新建项目(**画幅/分辨率选择**)+ 一键全自动/分步流水线;
- 任务中心: 全局任务表、实时日志抽屉、审批门的放行/取消。

## 9. 面板 ↔ API ↔ 领域函数对照(实现索引)

| 面板 | 主要 API | sd 领域函数 |
|---|---|---|
| ① 招聘 | GET detail.cast、POST run{op:cast}、**POST /cast(手动)**、/api/pool* | casting.run/**run_manual**、pool.scan、qwenimage.buildrefs、turntable |
| ② 服化道 | GET detail.materials/**assets_pick**、POST run{op:materials}、**POST/资产库 API** | materials.run、assetlib.* |
| ③ 编剧 | GET detail.script、POST run{op:script} | screenwriter.run(含 dialogue_cn) |
| ④ 分镜 | GET detail.cases、POST /dd、POST run{op:storyboard} | storyboard.run、lint.lint_dd、director._rebuild_prompt |
| ⑤ 导演 | GET detail.cases/gen_logs、POST run{op:generate/retake/regen} | director.shoot/retake、regen.run |
| ⑥ 审片 | GET detail.cases(review/frames)、POST run{op:review}、POST review/human | reviewer.review、has_passing_take |
| ⑦ 配音师 | GET detail.dub、POST run{op:dub}、**POST/DELETE bgm** | dubbing.run、av.mix_vo |
| ⑧ 制片 | POST run{op:deliver/master/produce/pipeline,**subs**}、GET detail.picks/deliverables/metrics | producer.deliver/deliver_master/produce、av.*、report.*、Metrics |

**资产库 API**: GET/POST /api/assets、DELETE /api/assets/{kind}/{id}、POST /api/projects/{n}/assets(预选);**设置 API**: POST /api/projects/{n}/settings(orientation/resolution)。

---

## 附:C28 起工作台新增能力(2026-09-24 下午迭代)

### 招聘 agent 扩展 —— 签约新演员(演员库页)

| 功能 | 交互 | 代价 |
|---|---|---|
| ＋ 签约主演 | 一句招聘要求 → agent 优化为 3 张**可编辑人设卡** → 试镜照(候选区) → 重掷/回炉/签约入库 | 卡片秒级(LLM);试镜照 ~4min/人;签约全链 ~20-30min/人 |
| ＋ 签约群演 | 数量+气质方向 → 默认直接全套入库(挂机);也可先试镜后勾选 | ~13-15min/人 |

机制:**候选区**(`工坊/候选/`,pool.scan 不扫、对招聘 agent 不可见);签约=三视图(v4 模板壳+VLM 自检)→裁正/侧身→3种子特写选优→搬入 `素材/角色X_名字`(字母自动顺延)。断点续跑:三视图存在即跳过;同目录孤儿 GPU 子进程自动等待。

### 审片 agent 扩展 —— 人工标记进入判定回路

- 「人工通过」= VLM 未过镜的**翻案**(分步流水线的审片门不再计为失败);
- 「否决并重拍」= 过镜镜**否决**(计入审片门失败清单,引导带建议重拍);
- 新增「🔁 一键重拍未过镜」:按审片建议批量外科手术重拍(人工翻案的不算),完成后提示复审。

### 工作台全局

- 任务历史落盘 `jobs.jsonl`(重启可查,含日志尾部);
- WS 断线自动重连并触发全量重同步(resync);
- `GET /api/health` 健康检查;409「项目忙」toast 带进度指引;
- 编剧面板新增「👁 预览 SRT」。
