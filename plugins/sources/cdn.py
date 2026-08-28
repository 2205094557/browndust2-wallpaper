# -*- coding: utf-8 -*-
r"""BD2（棕色尘埃2国际服）官方 CDN 来源插件。

协议（2026-08 实测）：
- 版本：PUT https://mt.bd2.pmang.cloud/MaintenanceInfo，body "EAQ="，响应 JSON 的
  data 字段 base64 解码后按 maintenance_info_pb2.MaintenanceInfoResponse 解析；
  HD 版本号 = market_info.bundle_version，SD = bundle_version_sd。
- catalog：GET https://cdn.bd2.pmang.cloud/ServerData/Android/{HD|SD}/{version}/catalog_alpha.json
  （Unity Addressables 格式，四个 base64 字段按 SerializationUtilities 布局解码）。
- bundle 条目：provider index == m_ProviderIds 中
  "UnityEngine.ResourceManagement.ResourceProviders.AssetBundleProvider" 的下标，且
  extra offset >= 0；extra 解出 {m_BundleName, m_Hash, m_BundleSize}。
- 下载：GET {base}/{bundle_key}；404 时用 re.sub(r"_[a-f0-9]+(?=\.bundle)", "", key)
  去掉 hash 后缀重试一次；.part 断点续传 + Range；大小校验以 catalog 的 size 为准。
"""

from __future__ import annotations

import base64
import json
import os
import re
import struct
import sys
import tempfile
import time
from pathlib import Path

import requests

from core.registry import SourcePlugin

# maintenance_info_pb2 相对路径兜底：确保打包（PyInstaller onedir/frozen）后也能加载。
_PB2_DIR = str(Path(__file__).resolve().parent / "cdn_proto_bd2")
if _PB2_DIR not in sys.path:
    sys.path.insert(0, _PB2_DIR)
import maintenance_info_pb2  # noqa: E402

MAINTENANCE_URL = "https://mt.bd2.pmang.cloud/MaintenanceInfo"
CDN_ROOT = "https://cdn.bd2.pmang.cloud/ServerData/Android"

BUNDLE_PROVIDER = "UnityEngine.ResourceManagement.ResourceProviders.AssetBundleProvider"

# 共享 bundle 前缀（bundle 级条目，位于 bundles TSV）
_SHARED_PREFIXES = {
    "spine": "common-ui-prefabs_assets_ui/prefabs/spine/illustspine_",
    "dating": "common-char-datingillust_assets_all_",
    "special": "common-ui-prefabs_assets_ui/prefabs/spine/illustspecial_",
}

_CHUNK = 256 * 1024  # 256KB
_ATTEMPTS = 3


class VersionInfo:
    """一次 handshake 的结果。"""

    def __init__(self, version, quality, base, raw_strings):
        self.version = version       # 如 "20260814115807"
        self.quality = quality       # "HD" / "SD"
        self.base = base             # 下载前缀 URL（含 quality 与 version）
        self.raw_strings = raw_strings  # {"catalog": version}，兼容旧接口形状


class _OT:  # SerializationUtilities.ObjectType
    AsciiString = 0
    UnicodeString = 1
    UInt16 = 2
    UInt32 = 3
    Int32 = 4
    Hash128 = 5
    Type = 6
    JsonObject = 7


def _i32(buf, off):
    return struct.unpack_from("<i", buf, off)[0]


def _read_object(buf, idx):
    """解码 key/extra 数据串中的一个对象；返回 (value, next_index)。"""
    t = buf[idx]
    idx += 1
    if t == _OT.AsciiString:
        n = _i32(buf, idx)
        idx += 4
        return buf[idx:idx + n].decode("ascii"), idx + n
    if t == _OT.UnicodeString:
        n = _i32(buf, idx)
        idx += 4
        return buf[idx:idx + n].decode("utf-16"), idx + n
    if t == _OT.JsonObject:
        n3 = buf[idx]
        idx += 1 + n3  # assembly name
        n4 = buf[idx]
        idx += 1 + n4  # type name
        n5 = _i32(buf, idx)
        idx += 4
        return json.loads(buf[idx:idx + n5].decode("utf-16")), idx + n5
    sizes = {_OT.UInt16: 2, _OT.UInt32: 4, _OT.Int32: 4}
    if t in sizes:
        return f"<int{t}>", idx + sizes[t]
    if t == _OT.Hash128:
        return "<hash128>", idx + 16
    if t == _OT.Type:
        return "<type>", idx + 4
    raise ValueError(f"unknown SerializationUtilities object type {t}")


class CdnSource(SourcePlugin):
    id = "cdn"
    name = "BD2 CDN"

    # backend 会注入实例属性；未注入时按类属性默认值处理
    proxy = None       # 非空时请求带 proxies={"http": proxy, "https": proxy}
    cache_dir = None   # Path，backend 注入 resources 下的缓存目录；None 时用系统临时目录

    # ---- 版本握手 ----
    def handshake(self, client="GLOBAL", quality="HD") -> VersionInfo:
        """向 MaintenanceInfo 拿最新 bundle 版本号，构造 VersionInfo 返回。"""
        quality = "HD" if str(quality).upper() == "HD" else "SD"
        headers = {
            "accept": "*/*",
            "accept-encoding": "gzip",
            "connection": "close",
            "content-type": "multipart/form-data",
            "host": "mt.bd2.pmang.cloud",
            "user-agent": "UnityPlayer/2022.3.22f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
        }
        proxies = self._proxies()
        last = None
        for attempt in range(_ATTEMPTS):
            try:
                resp = requests.put(
                    MAINTENANCE_URL, headers=headers, data="EAQ=",
                    proxies=proxies, timeout=(15, 60))
                resp.raise_for_status()
                payload = resp.json()
                if not isinstance(payload, dict) or "data" not in payload:
                    raise RuntimeError(f"response missing 'data': {str(payload)[:200]}")
                msg = maintenance_info_pb2.MaintenanceInfoResponse()
                msg.ParseFromString(base64.b64decode(payload["data"]))
                mi = msg.market_info
                version = (mi.bundle_version if quality == "HD"
                           else getattr(mi, "bundle_version_sd", "") or "")
                version = (version or "").strip()
                if not version:
                    raise RuntimeError(f"MaintenanceInfo 未返回 {quality} bundle 版本号")
                base = f"{CDN_ROOT}/{quality}/{version}"
                return VersionInfo(
                    version=version, quality=quality, base=base,
                    raw_strings={"catalog": version})
            except Exception as e:  # noqa: BLE001
                last = e
                if attempt < _ATTEMPTS - 1:
                    time.sleep(1 + attempt * 2)
        raise RuntimeError(f"BD2 MaintenanceInfo 请求失败: {last}")

    # ---- 工具 ----
    def _proxies(self):
        return {"http": self.proxy, "https": self.proxy} if self.proxy else None

    def _cache_root(self) -> Path:
        base = self.cache_dir
        if base is None:
            base = Path(tempfile.gettempdir())
        p = Path(base)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _catalog_json_path(self, info) -> Path:
        return self._cache_root() / f"bd2_catalog_{info.quality}_{info.version}.json"

    def _assets_tsv_path(self, info) -> Path:
        return self._cache_root() / f"bd2_catalog_{info.quality}_{info.version}.tsv"

    def _bundles_tsv_path(self, info) -> Path:
        return self._cache_root() / f"bd2_bundles_{info.quality}_{info.version}.tsv"

    def _download_to(self, url: str, dest: Path) -> bool:
        """整文件下载（.part + os.replace 原子替换），3 次重试。"""
        proxies = self._proxies()
        tmp = Path(str(dest) + ".part")
        for attempt in range(_ATTEMPTS):
            try:
                with requests.get(url, proxies=proxies, stream=True,
                                  timeout=(15, 120)) as r:
                    if r.status_code != 200:
                        raise RuntimeError(f"HTTP {r.status_code}")
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(_CHUNK):
                            f.write(chunk)
                os.replace(tmp, dest)
                return True
            except Exception:  # noqa: BLE001
                if attempt < _ATTEMPTS - 1:
                    time.sleep(1 + attempt * 2)
        return False

    # ---- catalog 解析与缓存 ----
    def catalog_csv(self, info) -> Path:
        """确保生成 assets 缓存 TSV，返回其路径。

        行格式：asset_key\\tbundle_key\\tsize（只含非 bundle 资产条目，
        每行带上其依赖链解析出的 bundle_key 与该 bundle 的大小）。
        """
        self._ensure_catalog(info)
        return self._assets_tsv_path(info)

    def bundles_tsv(self, info) -> Path:
        """确保生成 bundle 清单缓存 TSV，返回其路径。行格式：bundle_key\\tsize。"""
        self._ensure_catalog(info)
        return self._bundles_tsv_path(info)

    def _ensure_catalog(self, info) -> None:
        """两个 TSV 缓存齐备时直接返回；否则下载（或复用）catalog JSON 并重解析。"""
        assets_path = self._assets_tsv_path(info)
        bundles_path = self._bundles_tsv_path(info)
        if (assets_path.exists() and assets_path.stat().st_size > 0
                and bundles_path.exists() and bundles_path.stat().st_size > 0):
            return
        json_path = self._catalog_json_path(info)
        if not json_path.exists() or json_path.stat().st_size <= 0:
            url = f"{info.base}/catalog_alpha.json"
            print(f"[cdn] downloading catalog {url}")
            if not self._download_to(url, json_path):
                raise RuntimeError(f"catalog 下载失败: {url}")
        self._parse_catalog_json(json_path, assets_path, bundles_path)

    def _parse_catalog_json(self, json_path: Path, assets_out: Path, bundles_out: Path) -> None:
        """把 catalog JSON 一次性解析出 assets/bundles 两个 TSV（原子写入）。"""
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # m_BucketDataString -> dep_map（每桶入口下标） + key 数据偏移
        bucket_arr = base64.b64decode(data["m_BucketDataString"])
        num_buckets = _i32(bucket_arr, 0)
        dep_map = []
        key_offsets = []
        i = 4
        for _ in range(num_buckets):
            off = _i32(bucket_arr, i)
            i += 4
            n = _i32(bucket_arr, i)
            i += 4
            dep_map.append([_i32(bucket_arr, i + 4 * k) for k in range(n)])
            i += 4 * n
            key_offsets.append(off)

        # m_KeyDataString -> keys
        key_arr = base64.b64decode(data["m_KeyDataString"])
        keys = []
        for off in key_offsets:
            try:
                v, _ = _read_object(key_arr, off)
            except Exception:  # noqa: BLE001
                v = None
            keys.append(v)

        # m_EntryDataString 每行 7 个 int32；m_ExtraDataString 存 bundle 详情 JSON
        entry_arr = base64.b64decode(data["m_EntryDataString"])
        n_entries = _i32(entry_arr, 0)
        extra = base64.b64decode(data["m_ExtraDataString"])

        provider_ids = data.get("m_ProviderIds") or []
        try:
            bpi = provider_ids.index(BUNDLE_PROVIDER)
        except ValueError:
            raise RuntimeError(
                f"catalog 中找不到 AssetBundleProvider（m_ProviderIds={provider_ids[:3]}...）")

        bundles_by_entry = {}  # entry index -> (bundle_key, size)
        key_idx_of = [0] * n_entries
        dep_idx_of = [0] * n_entries
        i = 4
        for m in range(n_entries):
            i += 4  # num1
            provider_idx = _i32(entry_arr, i)
            i += 4
            dep_idx = _i32(entry_arr, i)
            i += 4
            i += 4  # num4
            extra_off = _i32(entry_arr, i)
            i += 4
            key_idx = _i32(entry_arr, i)
            i += 4
            i += 4  # num7
            key_idx_of[m] = key_idx
            dep_idx_of[m] = dep_idx
            if provider_idx == bpi and extra_off >= 0:
                try:
                    obj, _ = _read_object(extra, extra_off)
                except Exception:  # noqa: BLE001
                    obj = None
                if isinstance(obj, dict):
                    bkey = keys[key_idx] if 0 <= key_idx < len(keys) else None
                    bkey = str(bkey) if bkey is not None else ""
                    size = obj.get("m_BundleSize")
                    if bkey and size is not None:
                        bundles_by_entry[m] = (bkey, int(size))

        # bundles TSV（按 bundle_key 排序保证确定性）
        bundle_rows = sorted(bundles_by_entry.values(), key=lambda r: r[0])
        tmp_b = Path(str(bundles_out) + ".part")
        with open(tmp_b, "w", encoding="utf-8", newline="\n") as f:
            for bkey, size in bundle_rows:
                f.write(f"{bkey}\t{size}\n")
        os.replace(tmp_b, bundles_out)

        # assets TSV：非 bundle 条目 -> 依赖链第一个 bundle
        tmp_a = Path(str(assets_out) + ".part")
        written = 0
        with open(tmp_a, "w", encoding="utf-8", newline="\n") as f:
            for m in range(n_entries):
                if m in bundles_by_entry:
                    continue  # bundle 条目自身不进 assets TSV
                ki = key_idx_of[m]
                if not (0 <= ki < len(keys)):
                    continue
                k = keys[ki]
                if not isinstance(k, str) or not k:
                    continue
                resolved = self._resolve_bundle(m, dep_idx_of, dep_map, bundles_by_entry)
                if resolved is None:
                    continue
                bkey, size = resolved
                f.write(f"{k}\t{bkey}\t{size}\n")
                written += 1
        os.replace(tmp_a, assets_out)
        print(f"[cdn] catalog parsed: entries={n_entries:,} bundles={len(bundle_rows):,} assets={written:,}")

    @staticmethod
    def _resolve_bundle(entry_idx, dep_idx_of, dep_map, bundles_by_entry):
        """资产条目沿 entry_dep -> dep_map -> 第一个 bundle 条目解析。"""
        d = dep_idx_of[entry_idx] if 0 <= entry_idx < len(dep_idx_of) else -1
        if not (0 <= d < len(dep_map)):
            return None
        for b in dep_map[d]:
            if b in bundles_by_entry:
                return bundles_by_entry[b]
        return None

    # ---- 查询 ----
    def resolve_bundles(self, info, patterns) -> dict:
        """扫描 assets TSV（以及 bundle 级条目所在的 bundles TSV），返回
        {bundle_key: size}，asset_key 命中任一 pattern（re.Pattern，search 语义）即收集。"""
        self._ensure_catalog(info)

        pats = [re.compile(p) if isinstance(p, str) else p for p in patterns]

        def _hit(key):
            for p in pats:
                if p.search(key):
                    return True
            return False

        found = {}
        assets_path = self._assets_tsv_path(info)
        with open(assets_path, "r", encoding="utf-8") as f:
            for line in f:
                t1 = line.find("\t")
                if t1 < 0:
                    continue
                asset_key = line[:t1]
                if not _hit(asset_key):
                    continue
                rest = line[t1 + 1:].rstrip("\n")
                t2 = rest.find("\t")
                if t2 < 0:
                    continue
                bkey = rest[:t2]
                try:
                    found[bkey] = int(rest[t2 + 1:])
                except ValueError:
                    continue

        # 共享/语音等 bundle 级条目：bundle key 本身命中 pattern 也收集
        bundles_path = self._bundles_tsv_path(info)
        with open(bundles_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                t = line.find("\t")
                if t < 0:
                    continue
                bkey = line[:t]
                if bkey in found:
                    continue
                if not _hit(bkey):
                    continue
                try:
                    found[bkey] = int(line[t + 1:])
                except ValueError:
                    continue
        return found

    def shared_bundles(self, info) -> dict:
        """按前缀在 bundles TSV 中查找三个共享 bundle，返回
        {"spine": {"key": ..., "size": ...}, "dating": ..., "special": ...}。"""
        self._ensure_catalog(info)
        result = {}
        bundles_path = self._bundles_tsv_path(info)
        with open(bundles_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                t = line.find("\t")
                if t < 0:
                    continue
                bkey = line[:t]
                for tag, prefix in _SHARED_PREFIXES.items():
                    if tag in result or not bkey.startswith(prefix):
                        continue
                    try:
                        result[tag] = {"key": bkey, "size": int(line[t + 1:])}
                    except ValueError:
                        pass
        return result

    # ---- 下载 ----
    def download_asset(self, info, bundle_key, dest, size, cancel_event=None) -> bool:
        """下载一个 bundle 到 dest（完整目标路径）。

        差分（已存在且大小一致直接跳过）→ .part 断点续传（Range）→ 3 次重试 →
        403/404 去 hash 后缀重试一次 → cancel_event 置位时清 .part 返回 False。
        完成时按 catalog 的 size 校验，通过后 os.replace 原子落位。
        """
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        proxies = self._proxies()
        part = dest.with_name(dest.name + ".part")

        # 差分：已存在且大小一致
        if dest.exists() and dest.stat().st_size == size:
            part.unlink(missing_ok=True)
            return True

        current_key = bundle_key
        for attempt in range(_ATTEMPTS):
            if cancel_event is not None and cancel_event.is_set():
                part.unlink(missing_ok=True)
                return False
            headers = {}
            if part.exists() and part.stat().st_size > 0:
                headers["Range"] = f"bytes={part.stat().st_size}-"
            url = f"{info.base}/{current_key}"
            try:
                with requests.get(url, headers=headers, proxies=proxies,
                                  stream=True, timeout=(15, 60)) as r:
                    if r.status_code == 416:
                        # 服务器认为范围已超出（即已完整）
                        if part.exists() and part.stat().st_size > 0:
                            os.replace(part, dest)
                        return True
                    # BD2 CDN 对内容已轮换的失效 hash 不回 404 而是 403，
                    # 两者都需去 hash 后缀落到无 hash 兜底 URL（实测等价）
                    if r.status_code in (403, 404):
                        alt = re.sub(r"_[a-f0-9]+(?=\.bundle)", "", current_key)
                        if alt and alt != current_key:
                            current_key = alt
                            continue  # 同一尝试内换 URL 重试一次
                        return False
                    if r.status_code not in (200, 206):
                        if attempt < _ATTEMPTS - 1:
                            time.sleep(1 + attempt * 2)
                            continue
                        return False
                    mode = "ab" if r.status_code == 206 else "wb"
                    with open(part, mode) as f:
                        for chunk in r.iter_content(_CHUNK):
                            if cancel_event is not None and cancel_event.is_set():
                                f.close()
                                part.unlink(missing_ok=True)
                                return False
                            f.write(chunk)
            except Exception:  # noqa: BLE001
                if attempt < _ATTEMPTS - 1:
                    time.sleep(1 + attempt * 2)
                    continue
                return False
            # 以 catalog 的 size 为准校验
            if part.exists() and part.stat().st_size == size:
                os.replace(part, dest)
                return True
            if attempt < _ATTEMPTS - 1:
                time.sleep(1 + attempt * 2)
                continue
            return False
        return False