#!/bin/bash
# 终极重生成挂机: 天台纸灯全片(5镜) → 旧书店 q1/q4 → 复审 → 交付
set -x
cd ~/.zcode/workspace/default/shortdrama

# ── 1) 天台纸灯 5 镜 14 步重生成 ──
for c in taideng-q1 taideng-q2 taideng-q3 taideng-q4 taideng-q5; do
  if [ ! -f "projects/taideng/regen/$c-s14.mp4" ]; then
    python3 -m sd regen taideng $c --steps 14 2>&1 | tail -1
  fi
done
python3 - <<'PYEOF'
import subprocess
from pathlib import Path
proj = Path.cwd()/'projects'/'taideng'
clips = [str(p.resolve()) for p in sorted((proj/'regen').glob('taideng-q*-s14.mp4'))]
order = {f"q{i}": i for i in range(1,6)}
clips.sort(key=lambda c: order[Path(c).stem.split('-')[1]])
concat = proj/'concat_regen.txt'
concat.write_text(''.join(f"file '{c}'\n" for c in clips))
h = proj/'天台纸灯-14步重生成-横版.mp4'
subprocess.run(['ffmpeg','-y','-loglevel','error','-f','concat','-safe','0','-i',str(concat),
  '-c:v','libx264','-crf','16','-preset','slow','-c:a','aac','-b:a','160k',str(h)],check=True)
v = Path('/home/sunchendd/桌面/短剧-天台纸灯-taideng-14步重生成-竖版.mp4')
subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(h),
  '-vf','crop=432:768:456:0,scale=1080:1920:flags=lanczos,unsharp=5:5:0.35',
  '-c:v','libx264','-crf','16','-preset','medium','-c:a','copy',str(v)],check=True)
print('TAIDENG_ULTIMATE_DONE', v)
PYEOF

# ── 2) 旧书店 q1/q4 低分镜重生成 → 计入条历史 → 复审 ──
for c in shudian-q1 shudian-q4; do
  if [ ! -f "projects/shudian/regen/$c-s14.mp4" ]; then
    python3 -m sd regen shudian $c --steps 14 2>&1 | tail -1
  fi
done
python3 - <<'PYEOF'
import json
from pathlib import Path
# 把重生成条作为新 take 记入 shudian(供最佳条选片与复审采用)
sp = Path('projects/shudian')
st = json.loads((sp/'state.json').read_text())
for c in ('shudian-q1','shudian-q4'):
    mp4 = sp/'regen'/f'{c}-s14.mp4'
    st.setdefault('takes',{}).setdefault(c,[]).append(
        {"seed": st.get('storyboard_seed',42), "mp4": str(mp4.resolve()),
         "advice": "res_multistep14 重生成"})
(sp/'state.json').write_text(json.dumps(st, ensure_ascii=False, indent=1))
print('takes 已登记')
PYEOF
python3 -m sd review shudian --force 2>&1 | tail -1
python3 -m sd deliver shudian --force 2>&1 | tail -1
echo FINAL_REGEN_ALL_DONE
