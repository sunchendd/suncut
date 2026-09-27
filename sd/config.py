"""shortdrama 全局配置 —— 所有机器相关路径与冻结参数集中在此."""
import json
import os
from pathlib import Path

# ── 本机路径 ──
HOME = Path("/home/sunchendd")
SOL_PKG = HOME / ".zcode/workspace/default/Sana/models/minimax_h3/Sol-H3-Spark"
RUNTIME = HOME / "sol-h3-spark-runtime"
WORKSHOP = HOME / "桌面/AI角色工坊"
ASSET_LIB = HOME / "桌面/短剧资产库"         # 道具/场地 跨项目复用库
DESKTOP = HOME / "桌面"

# ── 绿联 NAS 同步(DXP4800Plus, fstab automount 到 /mnt/ugreen=素材共享) ──
# 凭据只在 /etc/cifs-creds/ugreen(仓库零凭据);NAS 离线=路径不存在=同步静默跳过。
# SD_NAS_ROOT=空 环境变量可临时禁用。
NAS_ROOT = Path(os.environ.get("SD_NAS_ROOT", "/mnt/ugreen/短剧工坊"))
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
PROJECTS = FRAMEWORK_ROOT / "projects"
SD_RUNTIME = RUNTIME / "shortdrama"          # JSONL 必须放 runtime 下(docker 挂载边界)
ZHIPU_KEY_FILE = HOME / ".zcode/v2/provider_config.json"

# ── 模型(智谱 BigModel Coding Plan) ──
LLM_BASE = "https://open.bigmodel.cn/api/coding/paas/v4"
LLM_TEXT = "glm-5.3"          # 编剧/分镜,重质量
LLM_FAST = "glm-5.3-flash"    # 轻量步骤
# 审片 VLM: glm-5.3-flash(默认,2026-09-25 用户指定替换 4.5v;同代更新更强);
# glm-4.5v 亦可(旧 A/B 偏差更小:0.48 vs 0.83,见 scripts/vision_ab.py)。
# 切换: 环境变量 SD_VISION_MODEL=glm-4.5v 后重启服务。
LLM_VISION = os.environ.get("SD_VISION_MODEL", "glm-5.3-flash")

# ── 视频生成端硬约束(Sol-H3 冻结值) ──
SHOT_FRAMES = 121
SHOT_FPS = 24
SHOT_SECONDS = SHOT_FRAMES / SHOT_FPS        # 5.0417s
VIDEO_W, VIDEO_H = 1344, 768
DEFAULT_BPM = 95                              # 每镜整 8 拍,剪点永远落在拍上
SHORT_TRIM = 2.6                              # duration_hint=short 的镜在剪辑表里裁到 2.6s(快切)
CHAR_SEED_BASE = 42
RETAKE_SEED_STEP = 1009                       # 单镜重拍换 seed 的步长(质数,避免撞)

# ── 交付端:横竖屏与分辨率(生成端固定 1344x768,裁切/缩放在交付时做) ──
RESOLUTIONS = {                               # name -> (横屏WxH, 竖屏WxH)
    "1080p": ((1920, 1080), (1080, 1920)),
    "720p": ((1280, 720), (720, 1280)),
    "480p": ((854, 480), (480, 854)),
}
ORIENTATIONS = ("portrait", "landscape")      # 缺省 landscape(竖版=16:9中心裁切再放大,清晰度降太多,2026-09-25 定)

# ── 配音(edge-tts;智谱 cogtts 在 Coding Plan 外需充值,故走本地免费链) ──
EDGE_TTS = HOME / "venvs/sdapi/bin/edge-tts"  # 回退: PATH 里的 edge-tts
TTS_VOICES = {                                # 配音师音色池(中文)
    "旁白-沉稳男声": "zh-CN-YunyangNeural",
    "旁白-温暖女声": "zh-CN-XiaoxiaoNeural",
    "男-阳光少年": "zh-CN-YunxiNeural",
    "男-低沉磁性": "zh-CN-YunjianNeural",
    "女-清亮活泼": "zh-CN-XiaoyiNeural",
    "女-知性温柔": "zh-CN-XiaoxiaoNeural",
}
NARRATOR_DEFAULT = "旁白-沉稳男声"
VOICE_PROFILES_FILE = "voice-profiles.json"  # 项目 audio/ 下，允许逐角色覆盖默认音色

# 制片曲库：只收录已核验授权、可追溯来源的音乐。曲目文件不提交到代码仓库。
MUSIC_LIBRARY = FRAMEWORK_ROOT / "music_library"
MUSIC_CATALOG = MUSIC_LIBRARY / "catalog.json"
MUSIC_SELECTION_FILE = "bgm-selection.json"

# infer.py 容器环境(run-solh3.sh 同款)
INFER_ENV = (
    f"SOL_H3_SPARK_RUNTIME_ROOT={RUNTIME} "
    f"SOL_H3_SPARK_QWEN_IMAGE=sol-h3-spark-qwen:latest "
    f"TRITON_CACHE_DIR={HOME}/.triton-solh3 "
    f"CPATH={HOME}/.pyheaders:{HOME}/.pyheaders/python3.12"
)


def zhipu_key() -> str:
    d = json.load(open(ZHIPU_KEY_FILE))
    return d["config"]["providerConfigRules"]["providerRules"][0]["config"]["access"]["apiKey"]
