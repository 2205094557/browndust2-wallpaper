# -*- coding: utf-8 -*-
"""BD2 CDN 插件端到端验证。

依次验证：
  a) handshake() 拿版本号
  b) catalog_csv() 生成 TSV 缓存（首次约 1-2 分钟：下载 63MB catalog + 解析）
  c) resolve_bundles(["char003892", "illust_dating14"]) 命中 bundle 数
  d) shared_bundles() 三个共享 bundle 的 key 与 size
  e) download_asset 下载 interaction_char003892 语音 bundle 并校验大小

运行：python D:\\codex\\browndust2-wallpaper\\tools\\test_bd2_cdn.py
（工作目录任意；脚本内把仓库根加入 sys.path）
"""
import re
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.sources.cdn import CdnSource  # noqa: E402

CACHE_DIR = Path(r"D:\codex\_bd2_research\cdn_cache")
DEST_DIR = Path(tempfile.gettempdir())


def count_lines(path: Path) -> int:
    n = 0
    with open(path, "r", encoding="utf-8") as f:
        for _ in f:
            n += 1
    return n


def main():
    cdn = CdnSource()
    cdn.cache_dir = CACHE_DIR
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # a) handshake
    print("== a) handshake ==")
    info = None
    for attempt in range(3):
        try:
            info = cdn.handshake("GLOBAL", "HD")
            break
        except Exception as e:  # noqa: BLE001
            print(f"  handshake retry {attempt + 1}: {e}")
    if info is None:
        raise SystemExit("FAIL: handshake 3 次均失败")
    print(f"  version={info.version}  quality={info.quality}")
    print(f"  base={info.base}")

    # b) catalog TSV 缓存
    print("== b) catalog_csv ==")
    assets_tsv = cdn.catalog_csv(info)
    bundles_tsv = cdn.bundles_tsv(info)
    a_lines = count_lines(assets_tsv)
    b_lines = count_lines(bundles_tsv)
    print(f"  assets  tsv: {assets_tsv}")
    print(f"  bundles tsv: {bundles_tsv}")
    print(f"  lines: assets={a_lines:,}  bundles={b_lines:,}")
    if a_lines <= 0 or b_lines <= 0:
        raise SystemExit("FAIL: TSV 缓存为空")

    # c) resolve_bundles
    print("== c) resolve_bundles ==")
    patterns = [re.compile("char003892", re.I), re.compile("illust_dating14", re.I)]
    found = cdn.resolve_bundles(info, patterns)
    print(f"  matched bundles: {len(found)}")
    for k, s in sorted(found.items()):
        print(f"    {k}  ({s:,} bytes)")
    if not found:
        raise SystemExit("FAIL: resolve_bundles 无命中")

    # d) shared_bundles
    print("== d) shared_bundles ==")
    shared = cdn.shared_bundles(info)
    for tag in ("spine", "dating", "special"):
        item = shared.get(tag)
        if item:
            print(f"  {tag}: {item['key']}  ({item['size']:,} bytes)")
        else:
            print(f"  {tag}: MISSING")
    for tag in ("spine", "dating", "special"):
        if tag not in shared:
            raise SystemExit(f"FAIL: 共享 bundle {tag} 未找到")

    # e) 下载 interaction_char003892 语音 bundle
    print("== e) download_asset ==")
    voice = cdn.resolve_bundles(info, [re.compile(r"interaction_char003892", re.I)])
    if not voice:
        raise SystemExit("FAIL: interaction_char003892 bundle 未命中")
    bkey, bsize = next(iter(voice.items()))
    dest = DEST_DIR / "bd2_test_interaction_char003892.bundle"
    ok = cdn.download_asset(info, bkey, dest, bsize)
    if not ok:
        raise SystemExit("FAIL: download_asset 返回 False")
    actual = dest.stat().st_size
    print(f"  key={bkey}")
    print(f"  expected={bsize:,}  actual={actual:,}  match={actual == bsize}")
    if actual != bsize:
        raise SystemExit("FAIL: 下载大小与 catalog 不一致")
    # 差分：二次调用应直接跳过
    ok2 = cdn.download_asset(info, bkey, dest, bsize)
    print(f"  second call (diff skip): {ok2}")
    if not ok2:
        raise SystemExit("FAIL: 差分跳过失败")

    print()
    print("PASS")


if __name__ == "__main__":
    main()