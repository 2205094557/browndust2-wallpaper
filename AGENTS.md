# AGENTS.md — 棕色尘埃2 立绘提取壁纸工具（browndust2-wallpaper）

> 本文件会被 Codex / Claude Code / Cursor 等 agent 在仓库内工作时自动加载。
> 本仓库由 azurlane-dynamic-wallpaper 复制改造，架构与铁律一脉相承；换游戏只换了
> CDN 协议、元数据与提取器实现（详见根技能 asset-extraction-pipeline）。

## 项目一句话
从棕色尘埃2(BD2)国际服官方 CDN 下载/提取 Spine 4.1 立绘（主立绘/约会/尊爵/Ultimate 演出）
+ 静态立绘 + 互动语音，Web 界面预览，导出 Wallpaper Engine 壁纸。

## BD2 协议速查（全部实测）
1. **版本**：`PUT https://mt.bd2.pmang.cloud/MaintenanceInfo`（body=`EAQ=`，Unity UA）→
   base64 protobuf（`plugins/sources/cdn_proto_bd2/maintenance_info_pb2.py`）→
   `market_info.bundle_version`(HD)/`bundle_version_sd`(SD)。
2. **目录**：`cdn.bd2.pmang.cloud/ServerData/Android/{HD|SD}/{version}/catalog_alpha.json`
   （Unity Addressables，~63MB；解码逻辑照 ReDustX：m_Bucket/Key/Entry/ExtraDataString 四个
   base64 段）。缓存为 TSV：`resources/metadata/bd2_catalog_*_*.tsv`（40 万资产行）+
   `bd2_bundles_*_*.tsv`（1973 bundle）。
3. **下载**：`{base}/{bundle_key}`，404 或 **403** 时 `re.sub(r"_[a-f0-9]+(?=\.bundle)","",key)` 去 hash 重试
   （服务端文件内容独立轮换而版本号不换时，旧 hash 报 403 Forbidden 而非 404；实测无 hash URL 恒有效）。
4. **资源模型（与碧蓝根本不同）**：主立绘/约会/尊爵 spine 存在**全角色共享大包**——
   `illustspine_*.bundle`(HD 86MB) / `common-char-datingillust_assets_all_*.bundle`(434MB) /
   `illustspine special: illustspecial_*.bundle`(438MB)，差分下载一次永久复用，**永不清理**；
   演出是每角色独立包 `isolated-cutsceneXXXXXX-group_*.bundle`；互动语音
   `interaction_charXXXXXX.bytes_*.bundle`（FEV+FSB5 容器）。
5. **角色 id**：服装 = `charXXXXXX`（如 Liberta·Hedonist = char003892）；
   约会 = `illust_datingN`；演出 = `cutscene_charXXXXXX`；静态 = `illust_charXXXXXX_NNN`。

## 常用命令
- **元数据**：`python tools/build_bd2_metadata.py`（catalog TSV + 社区角色表 →
  characters.json/ships.json；自动叠加 BD2DB 简体中文名，缺省自动选最新 catalog 缓存）→
  `python tools/build_bd2_skins.py`（→ skins.json）→ `python tools/build_local_index.py`
  （→ local_skins.json + 中文拼音检索 pinyin.json）。
- **中文名/头像**：`python tools/fetch_bd2_names.py`——从 BD2DB
  （browndust2-db.souseha.com，SPA 数据藏在 main→loadCharacters→db-characters 三级 JS 块里）
  抓简体角色名/皮肤名（按 gameId 与 charXXXXXX 直接对齐）+ 头像（icon_char{avatarId}.webp 转 jpg），
  产出 bd2db_names.json/avatars.json；「重建元数据」按钮的第一步即它（增量跳过已有头像）。
- **CDN 自检**：`python tools/test_bd2_cdn.py`（版本/目录/解析/差分下载全链路）。
- **端到端**：`tools/e2e_download_test.py` / `e2e_voice_test.py` / `e2e_export_test.py`。
- **开发栈**：`scripts/start_dev.py`（后端 8766 + Vite 5173 + 窗口）。⚠️ 改后端必须重启进程。
- **打包**：`python scripts/build_pack.py`（spec：`browndust2.spec`，产物 dist/browndust2-wallpaper）。

## 铁律（继承碧蓝全部铁律 + BD2 新增）
1. **BD2 贴图是直通 alpha**（RGB 未乘 A，二元 alpha 直方图实测）：
   `BD2_PREMULTIPLY_UPLOAD = true`（texImage2D 时浏览器预乘）+ `drawSkeleton(skel, true)`
   预乘混合。**模板 templates/wallpaper_spine.html 与 SpinePreview.vue 两处同步**。
   误设 false 的症状：深色背景正常、浅色背景整体洗白。
2. **Spine 4.1 运行时**：@esotericsoftware/spine-webgl@4.1.19（UMD 存
   `templates/spine41/spine-webgl-4.1.js`），实测兼容 4.1.11 skel。FALLBACK_UNITY_VERSION
   = `2022.3.22f1`（新版 bundle 版本头是 "0.0.0"）。
3. **无头截图验证陷阱**：canvas 的 CSS `opacity` 过渡（0→1, .8s）跑在合成器线程，
   `--virtual-time-budget` 不驱动它——截图恒定卡在 ~45% 透明度（人物洗白假象）。
   验证时注入 `#canvas{transition:none!important}` 或用黑白双图反推 alpha
   （`tools/alpha_probe.py` 方法）。真机 WE 不受影响。
4. **语音**：FEV+FSB5 容器（非 CriWare）。`tools/probe_bd2_voice.decode_voice`：
   定位 FSB5 魔数切片 → 临时 .fsb → vgmstream 逐 stream（CREATE_NO_WINDOW +
   utf-8 errors=replace）。cue 名 `CharXXXXXX_Int_{Mood}{N}_{variant}`，勿假设 48kHz。
5. **共享大包永不清理**：`_bundle_paths` 只返回独立小包；`skin_files` 对共享包类型
   只返回提取产物目录。
6. 碧蓝继承项：预览=导出同步、WE 属性首推跳过、run_tool 进程内加载、
   验收验产物不验接口、前端 API 只走 VITE_API_BASE。（2026-08 已完成碧蓝遗留清理：
   live2d 插件/模板/依赖、references/、wiki 同步工具与接口、鼠标追踪链路均已移除。）
7. **BD2 互动引擎单源**：`templates/shared/bd2-interact.js` 同时被预览（SpinePreview.vue
   静态 import）与壁纸模板（`<script src="bd2-interact.js">`，导出器拷贝）加载——改动必须
   只改这一份。实测 BD2 资产无官方分部位命中区（skel 零 BoundingBoxAttachment，
   VP_IllustViewer 仅全身 BoxCollider），交互 = 语义骨骼锚点分区 + `_faceN` 表情(track1)
   + `Int_{Mood}` 按情绪组随机语音；motion 整身反应有 12s 冷却，voiceCue 节流 600ms。

## 已知边界
- 尊爵皮 SpecialIllustN 与角色的映射关系数据源缺失，characters.json 的 special 字段暂空。
- GalleryView 的 `SPINE_INTERACTIVE` 白名单是碧蓝数据得出的静态清单，BD2 皮肤不在此列时
  互动模式仍可用（点击切表情），仅拖拽提示文案不显示；待改为运行时按骨架动画判定。
- 兼容性保留的旧标识：WE 一键应用副本标记 `.azl2d-marker`（改字节会让旧副本失去可清理性）、
  localStorage 键 `azl_*` 前缀、%APPDATA%rowndust2-wallpaper 用户数据目录——均不影响功能。
