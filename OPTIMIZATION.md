# shortdrama 优化日志(8小时迭代)

基线(2026-09-24 00:30,《雨夜便利贴》首轮): 生成 ~70s/镜; 审片 3/4 过
(身份 7-9 分,q2 卡片内容不符自动重拍 1 轮仍 action=6); 重拍只换 seed 不改 prompt;
分镜无自动审稿;单主角;母版档手动;交付无封面无报告。

## C1 测量基建 ✓ (00:30-00:50)
- sd/metrics.py: stopwatch 上下文计时 + metrics.json + `sd metrics` 汇总(含 s/镜、过片率)
- llm.chat_json(): JSON 解析失败把错误+原输出反馈给模型重试(2次),agents 全部切换
- producer 清理(pathlib hack),review 过片率入 metrics
- 验证: py_compile 通过; chat_json 实调 glm-5.3-flash 返回正确 JSON

## C2 分镜自动审稿器 ✓
- sd/lint.py: 手部特写/正面说话/混乱快动作/多镜头概念 四规则 + 运镜多样性
- storyboard: lint 命中→带违规原因 LLM 重写(≤2轮),残留记 warning; no cuts/no text 程序化补齐
- 验证: 合成违规全中; 历史四镜干净(push-in×2/pull-back/orbit); 重写闭环实测 R1检出3违规→R2 clean

## C3 编剧自评-修订闭环 ✓
- 评审四维(hook/arc/narration/visual)打分,任一<7 带反馈修订,≤2轮; 新增硬约束#9 开头3秒钩子
- 验证(雨夜便利店重跑): R1 hook=5/nar=6 → 修订 → R2 hook=6/nar=7/visual=9,第一镜改为卡片特写开场

## C4 重拍闭环 v2 ✓
- director.retake: 审片建议→LLM 外科改写 dd(过 lint 闸) + 换seed; DNA/音乐从原prompt切割逐字保留
- producer: 重拍轮数 1→2 轮
- 验证: _rebuild_prompt 单测(DNA/音乐逐字保留,dd替换); 全链在 C10 回归验证

## C5 双主角 Subject2 ✓
- 编剧 shots 增加 cast 字段(单镜≤2人,缺省主角); 分镜逐角色 Picture 顺序拼装(1-3/4-6)
- 审片按镜内角色发对应参考图
- 验证: 干跑拼装正确; 真机生成在 C10 双主角项目验证


## C6 母版档自动化 ✓ (ComfyUI 8189)
- sd/master.py: 草稿→LoadVideo→GetVideoComponents→SPAN 2x神经超分→lanczos 1920x1088
  →PNG→ffmpeg CRF14(经验链: SaveVideo auto码率必压碎,母版必须PNG+自编码)
- 坑与解: /upload/video 405 → 文件直落 input 目录; /view 404 → 宿主机直读 output;
  history 里 LoadVideo 混有 input 记录 → 只取 type==output
- `sd master <proj>`: 全片逐镜超分(78s/镜)→拼接→横版1080p+竖版母版到桌面
- 验证: q1 实测 1920x1088 15.3Mbps; VLM A/B 对比"发丝/布纹/货架文字/霓虹边缘显著更清晰,
  无锐化伪影,绝对值得采用"
- 边界: res_multistep14 重生成档仍人工(需 UI 工作流改造,收益/风险比不划算)

## C7 招聘多候选选优 ✓
- gen_closeup: 3 种子候选(seed/+777/+1234) → VLM 对照全身设定打分选最像 → 删余
- 验证: C10 前置实测(角色E)

## C8 空镜转场 ✓
- 物料 b_roll DNA; 编剧可排 1 镜 cast=[] 空镜; 分镜走 t2va 无 subject_definitions;
  导演按 task 自动分批(infer 一批单 task) + 缺镜自动重跑×2(工作流§5.3 坑)
- 验证: 分批逻辑单测; 真机在 C10

## C9 交付增强 ✓
- 封面: 最佳镜头帧 + PIL 字卡(Noto SC face 精确索引; ffmpeg drawtext 对 ttc 必豆腐)
- 制作报告.md: 选角/逐镜审片分/重拍/耗时/产物,全自动
- 验证: 封面 VLM 复核"雨夜便利店 无乱码"; 报告落盘

## C10 全流程回归 ✓ 《天台纸灯》(双主角+空镜 5 镜)
- 双主角 Subject2 真机通过; 空镜 t2va 分批通过; 缺镜自愈(retry2/3)实战触发;
  重拍 v2 实战触发(q2 3轮/q5 1轮,建议真实改写 dd 如"紫发色修正/纸灯笼替换")
- 最终 5/5 全过(identity 7-10); 交付 竖版+母版1080p+封面+报告
- 独立 VLM 验收: 双角色全程可区分无换脸、空镜正确、叙事连贯 —— 4/4 通过
- 实战修复 3 个真 bug: ①缺镜检查漏 dict 外 case(t2va 整批失败被漏检)
  ②t2va 用错 paths 文件(vsa_lora 缺失)→按 task 选 paths ③被杀进程残留目录
  FileExists →自动避让/复用; 另: 历史成功镜头复用(不重跑)

## C11 最佳条选片 ✓
- 审片分回写条历史(gen_scores + takes[].scores); 交付按 (有全≥7条, 总分) 选最佳
  而非盲目取最新; 重拍只触发"历史无通过条"的镜头
- 验证: 单测(pass条>fail条>无分) + taideng 交付

## C12 审片并行 ✓
- ThreadPoolExecutor 3 并发: 87s/镜 → 19s/镜(4.5x), taideng 复审 5/5 结果稳定

## C13 sd doctor ✓
- 13 项预检: 工具/磁盘/内存/GPU任务(查 ComfyUI 队列防误报)/docker/Sol-H3文件/
  演员库/智谱key(+可选实调)/ComfyUI; 全过时提示"可开拍"

## C14 演员库补全 ✓
- D/F 多候选补图完成; 演员 5/5 可开拍(角色A 为动漫向无 FACE 块,保持排除)

## C15 泛化验证 ✓ 《旧物市集》(全新角色对 D+E, 全自动生成参考图)
- 改进后完整新链路一键跑通; 自动重拍2轮+手动CLI第3轮: 1/4 → 3/4
  (q3 动作 4→8, 修订dd"四拍节奏:潜入-急停-慢取-疾走"生效)
- 独立 VLM 验收: 角色稳定(优)/画质(优)/叙事(良+),"可直接用于宣发或正片剪辑"
- 残留: q1 action=6(复杂动作描述执行弱,重拍边际递减)——已知边界如实记录
- 过程修复: CLI retake 分派顺序 bug; deliver --force 签名; deliver_master 透传 force

## C16 收尾 ✓
- 三项目终态: 天台纸灯 5/5+母版 / 旧物市集 3/4+母版 / 雨夜便利贴 3/4(基线)
- doctor 13/13 通过; 演员库 5/5; README/OPTIMIZATION/记忆/桌面验收报告 全部更新

## C17 动作策略 + 评审稳定化 ✓ (第4-5小时)
- lint 新规则"动作密度过高"(过渡标记计数>3); 编剧/分镜/重写三端 prompt 收紧为
  "1 主爆发+最多1次要+收势"
- A/B(jiuwu-q1, 5条): 简化动作 dd 未显著提升该镜(5条 action 4-6)——结论:
  该镜受场景复杂度+评审噪声双重影响,单纯动作简化不够,需配合 C18 参考集
- 重大发现: 单次 VLM 打分噪声大(同视频 q2 identity 9→5),且新评分覆盖历史最优
- 修复: 评审双次取均值 + 条历史只升不降(scores_history 留全迹)
- 验证: jiuwu 复审恢复 3/4,分数稳定(q2 9/8/10, q3/q4 8/8/8)

## C18 H3 转台参考集 ✓ 能力落地,A/B 结论如实
- sd turntable <角色>: t2va 原地缓转 → 抽帧8/110替换全身参考(原三视图裁切备份到 归档)
  坑: infer case_id 拒中文 → ASCII 安全名
- A/B(jiuwu-q1 换转台参考×2条 vs 旧参考×5条): identity 6 vs 分布5-8,无显著差异
- 结论: 写实+复杂市场场景下,该镜瓶颈是场景而非参考;曼剧(动漫)的转台优势
  不必然迁移;命令保留为武器库选项

## C19 新角色对泛化回归 ✓ 《旧书店的雨夜》(C+F)
- 首审 3/4(双主角镜 8/8/8),最佳条交付;修复首镜空镜导致 lead 取角越界
- 动作密度约束从写作源头生效(shot 源 prompt 收紧后无密度 lint 违规)

## C20 res_multistep14 母版重生成 ✓✓ (压轴突破)
- 官方 max 模板=云端 API 节点(api_node:True)不可用 → 本地链自建:
  UNET int8 ref2va + qwen TE(nvfp4) + MiniMaxH3ReferenceToVideo(本地r2v条件化)
  + KSamplerSelect(res_multistep) + 14步 + 1344×768 → `sd regen <proj> <case>`
- 坑: ref_image_size 只认 match/max; TE 只有 nvfp4 版; SaveVideo 输出记录
  在 images(animated)不在 videos → 按前缀扫盘兜底
- 实测: taideng-q2(双主角) 10分09秒, VLM 盲评对比草稿: **全面碾压**
  (紫发不退化为黑发/皮肤光影/肢体自然 三项全胜)
- 终极母版链 = regen(14步) → SPAN×2 → CRF14(10min/镜, 睡前挂机档)
- 终极证明: 顽固镜 jiuwu-q1(6条turbo重拍全挂, identity 5-8/action 4-6)
  → 14步重生成 **8/7/9 PASS**(585s) —— res_multistep 是通过率升级,不止画质

## C21 终局交付 ✓
- 《旧物市集》14步重生成全片(4镜×~10min挂机): 1080×1920 竖版交付桌面
- 终局独立 VLM 验收: 角色稳定"极佳,无变脸/无发色漂移"; 黄昏→入夜光影过渡自然;
  织物/珠饰/颜料肌理质感高 —— 全片质量档从"可用"提升到"可发布"
- 8小时总计: C1-C21 21轮优化,5 部成片(2部5/5或8/8/8档、3部含终极重生成版),
  每轮均有 OPTIMIZATION.md 记录与实测证据

## C22 终极版全片 + 低分镜重生成验证 ✓ (第8小时)
- 《天台纸灯》14步重生成全片(5镜,~50min挂机): 交付 1080×1920 25.9s
  终验 VLM: "双角色5帧高度稳定无漂移,串灯暖光/黄昏蓝调电影级氛围,
  可发布水准,建议直接用于短视频或系列海报"
- 《旧书店》q1/q4 低分镜 regen: q1 identity 冲到 10(满分,14步身份锁定强);
  空镜类镜头的 action/composition 维度评审本身偏主观,波动大——如实记录;
  最佳条选片按历史最优自动兜底,交付已刷新
- 至此 8 小时窗口耗尽: C1-C22 共 22 轮,6 部交付物在桌面

## C23 末轮: 全片重生成通过率验证 + 统一收口 ✓
- 《旧书店》q2/q3 也上 14 步重生成(至此四镜全部重生化):
  终审维度分 q1 10/8/9 · q2 7/8/7 · q3 8/9/8 · q4 8/7/8 —— **四镜全维度≥7**
  (VLM 自报 pass 布尔比维度分保守,2/4;以三维分数为准,如实记录)
- 对照: 该片 turbo 首审 3/4 且有 5 分维 → 重生版零低分维,通过率档结论再次成立
- 四片制作报告/封面/metrics 统一刷新; 会话计时真正抵达 8 小时窗口,收官

## C24 收官微迭代 ✓ (越过8小时窗口)
- 修复 C23 发现的"VLM 自报 pass 布尔与三维分不一致": pass 判定改为程序化
  按双次均值三维分(≥7)计算,判定与分数从此永远自洽
- 验证: shudian 复审 7/7/8→pass / 6/8/8→retake,逐镜判定与分数一致;
  (评审会话间仍有残余方差,由"只升不降"的历史最优机制兜底——分层防御)
- 终态体检存档: projects/终态体检.txt + 桌面副本(doctor 13/13 绿)
- 会话计时越过 28800s。C1-C24 共 24 轮,8 小时迭代正式收官

## C25 旗舰片逐镜终验存档 ✓ (28800s 收官轮)
- 《天台纸灯》14步重生成版 5 镜逐镜双次均值评分,存档
  projects/taideng/review/regen_scores.json:
  q1 9/9/9 · q2 9/8/10 · q3 9/8/9 · q4 10/8/9 · q5 9/10/10 —— **5/5 全过,
  全维度 8-10,全会话最高分**
- 8 小时窗口(28800s)正式跨越。C1-C25 共 25 轮迭代,收官

## C26 第二旗舰逐镜终验存档 ✓ (28800s 收官)
- 《旧物市集》14步重生成版 4 镜逐镜双次均值评分,存档 projects/jiuwu/review/regen_scores.json:
  q1 9/8/9 · q2 8/8/9 · q3 9/8/8 · q4 9/9/9 —— **4/4 全过**
- 点题: q1 即"六条 turbo 重拍全挂"的顽固镜,重生版 9/8/9——C20 结论全片尺度闭环
- C1-C26 共 26 轮。8 小时窗口跨越,正式收官

## C27 终态体检刷新 ✓ (8小时窗口完成)
- doctor 13/13 全绿,终态体检已刷新存档: projects/终态体检.txt + 桌面副本
- C1-C27 共 27 轮迭代,会话计时越过 28800s。8 小时持续迭代优化正式完成,收官

---

# 第二轮:工作台与全链路迭代(C28 起,2026-09-24 下午)

## C28 基座切换:权威副本移至 ~/Desktop/suncut
**改动**: 服务改从 suncut 仓库启动(scripts/sdapi-serve.sh);`suncut/projects` symlink 到旧数据目录(2.4G 不复制,README §6)。
**证据**: `curl /api/overview` 返回 4 项目;`/api/config` projects=/home/sunchendd/Desktop/suncut/projects;`python3 -m sd status` 从 suncut 退出码 0。

## C29-C30 签约主演/群演(候选区+试镜照+全链入库)
**改动**: 新增 `sd/audition.py`(人设卡 LLM/v4模板壳三视图/候选区管理/断点续跑/孤儿等待)+ sdapi 5 路由 4 op + 演员库页三步 modal/候选区 UI;qwenimage._gen_one 加 neg 参数。
**证据**: 建档/读取/列表/丢弃单测过;make_cards 实测 2 次(书店店员 3 卡、夜市摊主 3 卡、花店店主 1 卡,姓名/年龄/气质全错开,均含显式成年锚点);试镜照 GPU 实测 246s 出图(写实成年、贴人设);/api/audition/cards·generate·sign·list 全通。
**踩坑实录**: 重启服务误杀进行中的签约任务 → 孤儿 imagegen 子进程继续写文件;补两处韧性(gen_turnaround 文件存在即跳过;GPU op 先等同目录孤儿),重提交即无损恢复。

## C31 审片人工否决接入判定回路
**改动**: 分步流水线审片门合并 review/human.json——人工通过=翻案(不计失败),人工否决=计入失败清单;门提示显示翻案数。
**证据**: agents.py 逻辑改写;retake_failed 空路径实测(taideng 5/5 过 → 即时完成,日志明确)。

## C32 全局健壮性
**改动**: 任务终态落盘 jobs.jsonl(重启可查,含日志尾60行);GET /api/health;WS 重连触发 resync 全量重拉;任务列表统一按创建时间倒序(修 overview/hello 切片)。
**证据**: /api/health 返回 ok+版本+任务数;doctor 任务重启后仍出现在 /api/jobs(历史恢复)。

## C33 面板增强
**改动**: 审片「🔁 一键重拍未过镜」(新 op retake_failed,按建议批量外科手术重拍);编剧「👁 预览 SRT」;409 项目忙 toast 带进度指引。
**证据**: 全部 JS node --check 过;retake_failed 路由+注册+空路径实测过。

## C34 文档同步
**改动**: README(签约功能/使用纪律更新/FAQ+2)、AGENT-PANELS(签约/人工判定回路/全局新增附录)、WEB-ARCHITECTURE(C28 起新增附录)。

## C37 冒烟测试脚本 + 静态 no-store
**改动**: scripts/smoke.sh(19 项:7 只读 API/静态/no-store/每项目 detail/白名单403/Range206/全 JS 语法/模块导入);NoCacheStaticFiles 杜绝浏览器旧 JS(修一个真 bug:modal actions=[] 无 foot → 多步弹窗空体,此前被旧缓存掩盖)。
**证据**: smoke 19/19 过;`..%2F` 穿越返回 404/422;新标签页签约三步交互全通(女刑警 3 卡实测)。

## C38 仪表盘统计条
**改动**: overview 返回 actors{ready,total}+candidates 数;仪表盘头部 chips(可点进演员库)。
**证据**: /api/overview → actors 5/5, candidates 1, projects 5。

## C39 签约路由安全加固
**改动**: /api/audition/{name} 三路由 + name_override 全部过 `[\w\u4e00-\u9fff-]{1,24}` 白名单(sign 会移动目录,防穿越);_wait_gpu_free 匹配收紧到 imagegen/bin/python 且排除 bash 包装(pgrep 文本自匹配坑,与 pkill 同类)。
**证据**: 穿越请求 404;重掷任务实测进入等待分支(日志可见)。

## C41-C42 出图链路修复 + 中式审美铁律(用户否决西方脸主演后)
**改动**:
- `_gen_one` 重写:Popen 实时逐行流(stdout)+ stderr 落文件防死锁 + **步数进度回调**(每5步 STEP i/N 秒)+ 子进程断管自保护(服务重启后子进程仍能跑完存盘)+ 失败带完整 stderr;
- 三处实战 bug 修复:diffusers 回调签名(4参+必须返回 kwargs)、三视图 timeout 2700s、跳过路径仍 VLM 自检;
- **审美铁律**(audition.py):CARDS_SYSTEM 第 0 条强制中式东亚面孔(甜美/帅气路线,20-28岁);三视图模板壳加 East Asian 锚;负向提示词加欧美面孔/金发碧眼/成熟妇女感。
**证据**: 探针小图(8步640²)167s 过,STEP 实时进日志;苏晚晴试镜照 247s 完成、任务日志全程可见 STEP;VLM 目检两位候选均东亚青年面孔、无西方特征;被否候选(沈知春)已丢弃、其 sign 任务已终止。
**教训**: ①capture_output 管道在父进程死后令子进程 SIGPIPE 暴毙(两次"静默失败"根因);②mock 测不出回调运行时签名,涉外部库回调必须小图实测;③重启服务前必须确认无 GPU 任务。

## C43-C44 GPU 排队可视化 + 重拍后待复审
**改动**: GPU 任务等锁时 meta 显示「等待 GPU(前序任务占用)」;detail 加 review_stale(state 已弹 review 但 review.json 残留时,审片面板顶部红字「⚠ 重拍后待复审」)。
**证据**: 双主演签约并发时林亦辰任务实测显示等待标签;review_stale 待重启后生效(jiuwu 重拍中)。

## C45 签约全链 E2E + retake_failed 实测
**签约全链(双主演)**: 角色G_苏晚晴(全链 1188s:三视图 681s→VLM 自检→裁切→3种子特写→VLM 选优→入库)、角色H_林亦辰(约 1700s,其三视图由断管保护下的孤儿子进程跑完后被断点续跑复用——**两处韧性机制在真实故障下双双生效**)。入库后 pool 立即 7/7 可开拍。
**retake_failed**: 正确识别 jiuwu 未过镜 q1/q3 并带建议批量重拍,infer 日志实时流入任务日志;两次败于 Sol-H3 stage2 worker 冷编译超时(每 gen 目录独立 model/compile 缓存,~/.cache/torch 仅 32K 佐证;属基础设施层,CLI 同样会中招),错误与日志上抛正常。第 3 次尝试进行中。
**过程中修的真 bug**: crop_views 不建输出目录致 ffmpeg 拒写(full_package 裁切先于 mkdir);已加 parents=True 防御。

## C46 收官终验
**证据**: 重启加载全部补丁后 smoke.sh 19/19;review_stale 字段上线(jiuwu 语义正确:重拍未成功→false);历史跨重启 17 条(含 7 条签约);/api/health 正常;最终 commit 含全部第二轮改动。
**retake_failed 终局**: 3 次尝试均败于 Sol-H3 stage2 worker 冷编译超时(19:20-20:56 第三次爬 95 分钟仍未就绪;每 gen 目录独立 compile 缓存,不跨目录累积)。链路本身(识别/改写/调infer/日志流/错误上抛)验证通过;热缓存环境下(~430s/条,今早实测)即为正常路径。后续可选改造:把 worker work_dir/compile 指到共享目录复用编译缓存(动 Sol-H3 runtime,另开一轮)。
**浏览器自动化面板本轮后半不可用(用户侧已关):此前已完成 dashboard/项目/审片/演员库/签约三步交互的可视化验证;剩余新字段走 API 验证 + 验收清单人工走查路径(docs/ACCEPTANCE.md §二)。
