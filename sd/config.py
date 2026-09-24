"""shortdrama 全局配置 —— 所有机器相关路径与冻结参数集中在此."""
import json
from pathlib import Path

# ── 本机路径 ──
HOME = Path("/home/sunchendd")
SOL_PKG = HOME / ".zcode/workspace/default/Sana/models/minimax_h3/Sol-H3-Spark"
RUNTIME = HOME / "sol-h3-spark-runtime"
WORKSHOP = HOME / "桌面/AI角色工坊"
DESKTOP = HOME / "桌面"
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
PROJECTS = FRAMEWORK_ROOT / "projects"
SD_RUNTIME = RUNTIME / "shortdrama"          # JSONL 必须放 runtime 下(docker 挂载边界)
ZHIPU_KEY_FILE = HOME / ".zcode/v2/provider_config.json"

# ── 模型(智谱 BigModel Coding Plan) ──
LLM_BASE = "https://open.bigmodel.cn/api/coding/paas/v4"
LLM_TEXT = "glm-5.3"          # 编剧/分镜,重质量
LLM_FAST = "glm-5.3-flash"    # 轻量步骤
LLM_VISION = "glm-4.5v"       # 审片(支持图片输入)

# ── 视频生成端硬约束(Sol-H3 冻结值) ──
SHOT_FRAMES = 121
SHOT_FPS = 24
SHOT_SECONDS = SHOT_FRAMES / SHOT_FPS        # 5.0417s
VIDEO_W, VIDEO_H = 1344, 768
DEFAULT_BPM = 95                              # 每镜整 8 拍,剪点永远落在拍上
CHAR_SEED_BASE = 42
RETAKE_SEED_STEP = 1009                       # 单镜重拍换 seed 的步长(质数,避免撞)

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
