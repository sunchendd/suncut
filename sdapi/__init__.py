"""sdapi —— shortdrama 网页工作台服务层(FastAPI)。

物理上与 sd/ 同仓、逻辑上独立:本包只做编排/任务化/IO 包装,
不改动 sd/ 领域代码。启动: python3 -m sdapi 或 scripts/sdapi-serve.sh
"""
import sys
from pathlib import Path

# 保证任意 cwd 下都能 import sd( sdapi/ 与 sd/ 同级 )
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
