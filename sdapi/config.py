"""sdapi 服务配置 —— 环境变量可覆盖,默认只监听本机."""
import os
from pathlib import Path

from sd import config as sd_config  # noqa: F401  (复用 sd 的路径常量)

HOST = os.environ.get("SDAPI_HOST", "127.0.0.1")
PORT = int(os.environ.get("SDAPI_PORT", "8620"))
STATIC_DIR = Path(__file__).resolve().parent / "static"

# 媒体服务白名单根:JSON 里的绝对路径必须落在这些根下才允许 /api/media 读
MEDIA_ROOTS = [Path(sd_config.PROJECTS),
               Path(sd_config.SD_RUNTIME),
               Path(sd_config.WORKSHOP),
               Path(sd_config.DESKTOP)]

LOG_CAP = 4000        # 每个任务在内存里保留的日志行数上限
TAIL_POLL = 1.5       # gen-*.log 轮询周期(秒)
