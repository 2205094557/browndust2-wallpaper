# 预览 vs 导出 相似性对比：逐对像素差取最优匹配 + 帷幕扫掠范围对比
import numpy as np
from PIL import Image
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / 'tools' / '_framing_shots'


def load_gray(p, size=(160, 90)):
    """返回 (亮度归一化帧, 原始灰度帧)：归一化帧比几何，原始帧比帷幕亮度区域"""
    img = Image.open(p).convert('L').resize(size)
    a = np.asarray(img, dtype=np.float32)
    norm = (a - a.mean()) / (a.std() + 1e-6)
    return norm, a


def bright_centroid(arr):
    """亮色（帷幕）区域的水平质心与宽度占比"""
    mask = arr > 170
    if mask.sum() < 20:
        return None, None
    xs = np.where(mask.any(axis=0))[0]
    w = arr.shape[1]
    return (xs.min() + xs.max()) / 2 / w, (xs.max() - xs.min()) / w


prev = sorted((SHOTS / 'simprev').glob('p*.png'))
exp = sorted((SHOTS / 'simexp').glob('e*.png'))
P = [load_gray(p) for p in prev]
E = [load_gray(e) for e in exp]
print(f'预览帧 {len(P)} | 导出帧 {len(E)}')

# 逐对最优匹配（归一化帧比几何）
best = (1e9, -1, -1)
for i, (pn, _) in enumerate(P):
    for j, (en, _) in enumerate(E):
        d = np.abs(pn - en).mean()
        if d < best[0]:
            best = (d, i, j)
diff, pi, ei = best
print(f'最优匹配: 预览#{pi} vs 导出#{ei}  归一化差={diff:.3f}  几何相似度={(1 - diff / 8) * 100:.1f}% (标准化差<0.5 即高度相似)')

# 帷幕扫掠范围（原始灰度帧）
def sweep(frames, tag):
    cs, ws = [], []
    for _, raw in frames:
        c, w = bright_centroid(raw)
        if c is not None:
            cs.append(c)
            ws.append(w)
    if cs:
        print(f'{tag} 帷幕质心范围: {min(cs):.2f}~{max(cs):.2f} (跨度 {max(cs) - min(cs):.2f}) | 宽度范围: {min(ws):.2f}~{max(ws):.2f}')
    return cs, ws

csP, wsP = sweep(P, '预览')
csE, wsE = sweep(E, '导出')

if csP and csE:
    lo = max(min(csP), min(csE)); hi = min(max(csP), max(csE))
    span = max(max(csP), max(csE)) - min(min(csP), min(csE))
    print(f'扫掠区间重叠度: {(hi - lo) / span * 100:.0f}%' if span else '')
