# -*- coding: utf-8 -*-
"""黑白双图逐像素反推 canvas 有效 alpha：a = 1 - (white-black)/255。"""
from PIL import Image

b = Image.open(r"D:\codex\browndust2-wallpaper\tools\_cmp_black.png").convert("RGB")
w = Image.open(r"D:\codex\browndust2-wallpaper\tools\_cmp_white.png").convert("RGB")
pb, pw = b.load(), w.load()
# 人物上的特征点（皮肤/红腰封/黑色和服/头发）
points = {
    "腿部皮肤(608,470)": (608, 470),
    "大腿(615,430)": (615, 430),
    "脸(585,90)": (585, 90),
    "头发(640,40)": (640, 40),
    "红色和服内衬(556,420)": (556, 420),
    "黑色和服(650,300)": (650, 300),
    "团子串(505,150)": (505, 150),
}
for name, (x, y) in points.items():
    cb = pb[x, y]
    cw = pw[x, y]
    alphas = [round(1 - (cw[i] - cb[i]) / 255, 3) for i in range(3)]
    print(f"{name}: black={cb} white={cw} -> alpha≈{alphas}")
