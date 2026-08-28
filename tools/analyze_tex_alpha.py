# -*- coding: utf-8 -*-
"""分析 BD2 spine 贴图的 alpha 分布与预乘特征。"""
import collections

from PIL import Image

im = Image.open(
    r"D:\codex\browndust2-wallpaper\resources\extracted\spine\char003892\char003892.png"
).convert("RGBA")
w, h = im.size
px = im.load()
hist = collections.Counter()
opaque_samples = []
for y in range(0, h, 16):
    for x in range(0, w, 16):
        r, g, b, a = px[x, y]
        hist[a // 32] += 1
        if a >= 250 and len(opaque_samples) < 5:
            opaque_samples.append((x, y, r, g, b, a))
print("alpha 直方图(桶*32):", dict(sorted(hist.items())))
print("不透明样本:", opaque_samples)
viol = tot = 0
for y in range(0, h, 8):
    for x in range(0, w, 8):
        r, g, b, a = px[x, y]
        if a > 0:
            tot += 1
            if r > a or g > a or b > a:
                viol += 1
print(f"RGB>alpha 违例: {viol}/{tot} (高比例=直通alpha, 低比例=预乘)")
