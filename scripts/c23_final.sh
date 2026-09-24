#!/bin/bash
cd ~/.zcode/workspace/default/shortdrama
for c in shudian-q2 shudian-q3; do
  [ -f "projects/shudian/regen/$c-s14.mp4" ] || python3 -m sd regen shudian $c --steps 14 2>&1 | tail -1
done
python3 - <<'PYEOF'
import json
from pathlib import Path
sp = Path('projects/shudian')
st = json.loads((sp/'state.json').read_text())
for c in ('shudian-q2','shudian-q3'):
    mp4 = sp/'regen'/f'{c}-s14.mp4'
    st.setdefault('takes',{}).setdefault(c,[]).append(
        {"seed": 42, "mp4": str(mp4.resolve()), "advice": "res_multistep14 重生成"})
(sp/'state.json').write_text(json.dumps(st, ensure_ascii=False, indent=1))
print('takes 登记')
PYEOF
python3 -m sd review shudian --force 2>&1 | tail -1
python3 -m sd deliver shudian --force 2>&1 | tail -1
echo C23_GPU_DONE
