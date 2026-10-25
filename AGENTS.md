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
  端口可覆盖：`BD2_BACKEND_PORT=8767 BD2_VITE_PORT=5174 python scripts/start_dev.py`
  （与兄弟项目并存时用：碧蓝/奥拉等工具默认也是 8766/5173 + 同名 `backend_server.py`
  /`web_main.py`）；`python scripts/start_dev.py --stop` 一键关闭。
- **打包**：`python scripts/build_pack.py`（spec：`browndust2.spec`，产物 dist/browndust2-wallpaper）。

## 铁律（继承碧蓝全部铁律 + BD2 新增）
1. **BD2 贴图是直通 alpha**（RGB 未乘 A，二元 alpha 直方图实测）：
   `BD2_PREMULTIPLY_UPLOAD = true`（texImage2D 时浏览器预乘）+ `drawSkeleton(skel, true)`
   预乘混合。**模板 templates/wallpaper_spine.html 与 SpinePreview.vue 两处同步**。
   误设 false 的症状：深色背景正常、浅色背景整体洗白。
2. **Spine 4.1 运行时**：@esotericsoftware/spine-webgl@4.1.19（UMD 存
   `templates/spine41/spine-webgl-4.1.js`），实测兼容 4.1.11 skel。FALLBACK_UNITY_VERSION
   = `2022.3.22f1`（新版 bundle 版本头是 "0.0.0"）。
   **默认动画选择（pickAnim，模板+SpinePreview 两处同步）**：优先 `loop_N`/`idle`/`normal`，
   跳过转场/演出开场（`chain`/`cut_*`/`login`）。Ultimate 演出骨架动画结构常为
   chain(3.6s)/cut_A/cut_B/loop_1/loop_2——默认选到 chain 时其 t=0 人物不在构图，
   取景框错 → 导出后“只有背景、人物不可见”（headless 实渲染复现 + 修复验证）。
   **Ultimate 多阶段背景**：演出每阶段（loop_N/cut_*）各配一组独立背景 backN（组内
   -1/-2 变体/分层），build_local_index 把全部组收进 asset.bg_sets（{组号: 文件}，
   基底 backN.png 优先，默认 layers.bg=组 1），导出拷全部 + 注入 BG_SETS；预览
   （SpinePreview.vue initBgSets/activeBgSetImg）与壁纸模板按当前动画切背景组，
   共享映射 WallpaperLayout.bgSetForAnim，两端一致。**bgSetForAnim 阶段标记识别
   （2026-10 实测 12 个演出皮此前恒不换背景后扩展，优先级从先到后）**：① 下划线
   锚定尾号 `loop_2`/`cut_A_2`（字母+尾号并存时尾号是阶段——老皮肤实测行为，最
   优先防回归）；② 前缀单字母 `A_cut`/`B_cut_idle`/`A_cut_w1`（变体尾缀不干扰）；
   ③ 中缀 `_X_`（取最左，阶段字母在变体后缀前：`cut_a_hand_f` 取 a）；④ 尾缀
   `_X`（大小写都认：`cut_B`/`cut_b`）；⑤ 紧贴尾号 `loop2`/`cut_B2`。勿改顺序
   ——①②互换会把 cut_A_2 型皮肤改死。剩余 4 个皮肤（003101/060701/061101/060402）
   动画只有 [cut_A, loop] 两个而背景组 ≥2，多余组无对应动画，映射无解（数据限制）。
   映射覆盖探针 `tools/_bgset_anim_scan.js`（含新旧映射回归对比，应 0 真回归）。
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
   第二代约会章节模型（2026-08 附件状态指纹实测 dating11/14/18/20，勿回退）：
   点击按【章节图行走】推进故事：本章 mix 步进（回本章家 idle）→ 章内 reaction →
   过桥进下一章（桥终态=新章家 idle，全程附件连续；打断/自然播完均实测 0 残留）。
   配对与 motion 终态必须实测（computeMotionTargets，宿主注入 createState）：
   家 idle = 本章首段入场跳变（t=0.05 附件差）最小的 idle——多数皮肤按数字
   （mix{K}↔idle{K}），dating20 实测 mix5→idle4、mix7→idle6 错位一章，按数字配对
   会回错待机；motion 终态 = 从家 idle 接播、结束态与各 idle 比附件差
   （如 dating11：1_9→idle2、2_1→idle3、3_0/4_0→回基地）。
   引擎留有 LOCK_CHAPTER 开关（默认 false）——用户若再报"待机不该切换"可启用
   锁章（只循环最低编号章）。注意锁章下 motionReturnDist>30 的跨章桥不进列表。
   mix 语法 `mix{章}_{步}[_{变体}][_{long|loop|end[N]}]`，loop 停留段配对为前一步
   hold（播完循环 hold 等下次点击）。实测放在皮肤加载阶段预热（ dating20 约 0.5s，
   别放首击）。回归探针：`node tools/_mix_probe/scan_all_skins.js`（22 个 mix 皮肤
   应 0 问题，2026-10 含 dating22 阶段骨架合并 profile）；打断残留探针
   `node tools/_mix_probe/interrupt_ghost_test.js`（应全 0；测试对是 dating11 硬编码，
   测别的皮肤需自配对）。
   引擎 VERSION（当前 v8-20261025）显示在调试 HUD，排障先确认页面加载的版本——
   开发栈进程存活期间模板文件的 HMR 可能失效，怀疑陈旧先强刷。
   **链式章节（2026-10 dating12「Stranger Bunny」实测，v8）**：两代章节模型并存——
   锚定型（dating14/21/d22：段落起止≈家 idle，每步播完回家不闪，点击步进）与
   链式型（dating12 章1 47 段、dating11 章1、dating20 章5/7：相邻段终点→起点差
   0~8 连续演出，但段落起点距家 idle 达 100~300，插 idle 必闪现别的姿态=用户报的
   "动画不连贯跳出其他位置的动画"）。判据与处理（computeMotionTargets 的
   buildChainNext，对锚定皮肤零影响）：相邻段 end→start 差 ≤30 且后段起点距家
   >30 → chainNext[A]=B，宿主 complete 时 advanceAuto 自动续播（hold/loop 停留段
   不参与链、优先暂停）；链式章节的跨章桥 motion 顺接末段（dating12 motion1_35
   终点=idle2 差 0）。点击推进与自动续播共用同一播放列表指针，链中点击=无缝跳进
   下一段，不会错位。
   **多章约会皮阶段骨架（2026-10 实测 dating22=阿奇拉·被封印的欲望）**：官方把
   约会皮的每个章节场景做成独立骨架（illust_dating22_1=蜡烛人偶室 mix1 章 21 段、
   _2=影子场景 mix2 章 28 段，槽位前缀 ID1/ID2，各带自有 atlas 与贴图），提取后
   全部落在基础目录，仍是**一个条目**——按既定章节行走规则跨骨架推进，不分卷。
   机制：`build_local_index.spine_skel_sets` 在目录内 skel 干名全部匹配
   `{目录名}_N` 时把全部骨架收进 `asset.skel_sets`（{卷号: skel 名}；老目录如
   illust_dating1 混入的跨编号复制品不满足全匹配，保持旧行为）；预览与壁纸模板
   全量预载、只渲染当前阶段（isActiveSkel 过滤渲染/取景/命中区），引擎
   `computeMotionTargets` 按 animPhase 阶段隔离探测，motion 终态与同阶段 idle
   最小差 >30 判为跨阶段桥（实测 dating22 motion1_21 终态差 97 = 第一章终章
   演出，桥落第二章 idle2；motion2_0 差 1 = 章内反应），宿主 syncActivePhase
   在播放到别的阶段动画时换幕+重新取景。引擎 VERSION v8-20261025。
   **motion 型互动（v8，2026-10 出云天花 Special Date 实测）**：新世代皮肤的
   spine 只有 idle+motion（无 _faceN 无 mix），detect 判为 style 'motion'——
   点击播 motion 整身反应（与第一代表情皮同源但无表情可叠，无互动语音包）。
   共享大包 datingillust 会随新约会皮轮换 hash（旧 hash 内容没有新章），本地旧包
   命中 403 时按无 hash URL 重下（铁律 3）；447MB 大包的 UnityPy 提取要 1-3 分钟，
   界面"正在提取 Spine 骨架"阶段慢是正常现象（bundle 已缓存时不再重新下载）。
8. **Cutscene Bundle 多套骨架贴图冲突防护**：部分演出包（如 `isolated-cutscene004201-group_*.bundle`
   帕莱特·惊悚之梦、`isolated-cutscene004091/003803/066402`）内打包了多套骨架
   （`cutscene_charXXXXXX` 主骨架与 `_1`/`_camera` 等次要过场骨架）。提取器
   `plugins/extractors/spine.py` 预扫骨架所在 container 目录锁定目标骨架（优先匹配
   out_dir 名，否则取 skel 最大者），按【目录前缀 + 被拒骨架干名】双重过滤次要骨架的
   skel/atlas/贴图（干名匹配覆盖两套骨架同目录的情况），并在重提时自愈删除输出目录里
   旧版提取残留的次要骨架文件——残留会让预览多层骨架叠加渲染、"几个动画重叠在一起"
   （2026-10 cutscene004091 实测，旧提取早于本防护）。疑似受影响的皮肤重提即可自愈。
9. **预览↔导出取景一致（16:9 cover 裁切）**：预览 stage 恒为 16:9，WE 侧画布是
   100vw×100vh（16:10/21:9…）。`templates/wallpaper-layout.js` 的 `viewportFrame` /
   `coverZoomFactor` 在所有尺寸计算处统一按 16:9 取景框 + cover 裁切：
   `spineCamera` 与 `charOffsetWorld` 都用取景框（不是实际画布）当基准，相机 zoom 再
   除以 cover 系数铺满画布。**症状回归判据**：同一 scale/offset 下，模型高度占画布
   **恒为 MARGIN(98%)**（见 `tools` 里 node 数值校验），宽屏只是两侧裁切。
   切勿改回「直接用 canvas.clientWidth/Height」——那会让 WE 与预览大小不一致。
   **画面模式融合缩放（2026-10）**：滚轮缩放必须是"整张构图照片式缩放"——相机
   zoom（人物）、bgScale（CSS 背景）与三类偏移锚点（offsetX/Y、charOffset、
   bgOffset）都按同一比例 k=next/scale 变化（见 SpinePreview `onCanvasWheel`
   stage 分支）；CSS 图片背景（GalleryView `autoBgStyle`）的锚点必须 =
   画面中心 + (整体偏移 + 背景偏移)，与 WebGL drawBg 的世界锚定同式，导出端
   `bg_css_for_skin` 同式（vw/vh）。漏掉任一项的症状：画面/人物/背景模式滚轮
   缩放时人物与背景绕各自锚点生长，越缩分离越大（此前实测复现 + 修复验证，
   探针 `tools/_zoom_fusion_check.js`）。
   **人物旋转（2026-10）**：调节面板「旋转」滑块（-180~180°，正=顺时针）+
   导出选项 `rotation` → 模板 `CHAR_ROTATION`（export_defaults 烘内联，同
   CHAR_OFFSET 不生成 WE 控件）。实现：渲染期把旋转右乘进投影矩阵
   （`charRotationMatrixValues`，列主序），**只转人物层**——背景批先 `end()`
   flush、改写 projectionView 后再画人物层（enableRenderer 会重绑 MVP，下一帧
   `camera.update()` 重建矩阵，无需还原）；**两个支点语义不同，勿混用**——渲染
   支点 = 人物并集中心 + charOffset（偏移是旋转后的刚体平移，拖动时整个旋转
   人物跟随平移）；取景支点 = 仅人物并集中心（**不含 charOffset**），否则拖动
   人物时旋转 AABB 跟随平移，背景矩形锚在 AABB 中心会被拖着走（"拖动人物
   背景跟着扭"实测病根）；取景框按旋转后 AABB 外扩
   （`rotateBoundsAabb`）保证任意角度完整可见，背景 cover 同源扩大。点击命中用
   `unrotateWorldPoint` 取逆映射回未旋转世界坐标（预览 hitAreaAt /
   BD2Interact.decide 与模板 hitNameAt 共三处）。预览 SpinePreview.vue 与模板
   wallpaper_spine.html 两端同步，数学探针 `tools/_rotation_check.js`。
   导出链路：前端选项 `rotation` 必须经 `backend_server._export_project` 的
   **选项白名单**透传（漏加 = 导出恒 0°，2026-10 实测）；`render_template` 有
   未替换占位符护栏（漏键时直接报错而非产出黑屏壁纸——旧进程+新模板会把字面
   `{{XXX}}` 烘进 JS 使整段脚本语法死亡、人物背景全灭，铁律"改后端必须重启
   进程"的高发事故面）。运行时探针 `tools/_wp_runtime_probe.js`：stub DOM/WebGL
   跑导出产物的启动+渲染帧，抓 JS 异常与关键状态。
10. **WE 封面 = 预览截图**：`project.json` 的 `preview` 必须是用户看到的构图。
   BD2 骨架贴图是**整张 2048² 平铺图集**（挑「assets 里最大的 PNG」会得到一堆碎片），
   挑扩图背景则只有背景没有角色——旧实现两种都不是封面。现状：前端导出/应用时
   `capture()` 截预览画布（16:9）→ `previewImage` 随请求发送 → 后端
   `write_preview_from_data_url()` 裁成 16:9 写 `preview.jpg`；截不到才回退
   背景图/图集/纯色兜底。改导出协议时务必保留 `previewImage` 透传。
11. **壁纸多预设（2026-10）**：一个皮肤可存多套「动画 + 背景 + 构图」预设，导出后
   在 WE 属性面板用「预设」下拉一键切换（如 Ultimate 的 loop/loop_2 各一套构图）。
   链路：GalleryView「壁纸预设」面板（保存当前/预览/删除，localStorage
   `azl_wp_presets_{skinKey}` 持久化，≤8 个）→ 导出选项 `presets` 数组 →
   `_export_project` 白名单透传（**漏加白名单 = 前端传了后端收不到**，铁律 9 同款
   事故面）→ 导出器 `_sanitize_presets` 清洗 + 每预设拷背景图（同名不同源加序号
   防覆盖）/`bg_css_for_skin` 算 CSS，烘 `PRESETS_JSON`；有预设时**主占位值
   （SCALE/OFFSET/ANIMATION/BG_CSS/HIDE_DEFAULT_BG…）取首个预设**，且只要任一
   预设为 auto 就必须拷官方 bg_sets（预设间 auto/自定义可混搭）→ 模板
   `applyPreset`（版式变量 + bg-layer CSS + playAnim + applyLayout 一次应用），
   属性监听首推恢复 WE 保存的选择、变更推送即切换。无预设时 PRESETS=[]，行为与
   旧版完全一致。回归：`node tools/_wp_runtime_probe.js <项目>` 的 PRESET-CHECK
   （首推恢复 + 切换推送，验证 anim/SCALE/OFFSET_X 逐项）。

## 背景超分与扩图工作流（移植自 NIKKE 工具）
- **目录分工**：
  | 路径 | 角色 | 说明 |
  |---|---|---|
  | `resources/background/` | 官方场景背景 | 放入场景图后自动扫描并生成缩略图 |
  | `resources/output/` | **导出目录**：`导出扩图` 把当前背景复制进来（待扩图） | 中转目录，生成 `扩图说明.txt` |
  | `resources/input/` | **扩图成品库（即背景库本身）**：扩图成品放这里即可选用 | 软件不复制文件——删掉 input 里的图片即从列表消失；同名覆盖官方背景 |
  | `resources/preview/` | 超分产物临时缓存（`*_preview.png`） | 退出/启动软件自动清理，母图持久 |
- **工作流规则**：
  - 导出到 output → 外部工具扩图 → 成品放进 input → 点「导入扩图」刷新列表（打开背景弹窗时也会自动扫描）；
  - **input 就是成品库**（2026-09 改）：`导入扩图` 只做「扫描 + 生成缩略图」，不复制、不转换、不另存。
    前端「自定义 / 扩图」分类列的就是 input 里的文件，卡片 ✕ 删的也是 input 里的文件；
    旧版 `resources/custom/` 持久库已废弃，启动时 `migrate_legacy_custom()` 幂等并入 input
    （同名同内容丢弃重复份，不同内容加 `_legacy` 后缀保留，不静默删文件）；
  - 与同名官方背景字节一致的文件（未扩图原样丢回）只在提示里点名，不隐藏；
  - 缩略图生成到 `resources/thumbnails/background/`（成品库条目带 `__custom` 后缀，避免与同名官方图互相覆盖）；
  - 背景解析统一走 `resolve_background_file`（顺序：input → official → output → preview）；
  - 背景超分支持 Waifu2x / Real-CUGAN / Real-ESRGAN（2x/4x、降噪、TTA 多角度采样、4x->2x Lanczos 超采样、透明通道拆分保护）；
  - 导出壁纸（`wallpaper_spine.py`）将所选背景拷贝至壁纸 `assets/` 目录并烘入 `BG_CSS`。

## 已知边界
- 尊爵皮 SpecialIllustN 与角色的映射关系数据源缺失，characters.json 的 special 字段暂空。
- **社区角色表（BD2-L2D-Viewer character_list.ts）**：本机已安置于
  `D:\codex\_bd2_research\character_list.ts`（2026-10-25 从
  `cdn.jsdelivr.net/gh/Jelosus2/BD2-L2D-Viewer@main/src/utils/character_list.ts` 获取，
  github 直连被墙走 jsDelivr；234 服装，含新世代联动皮身份）。表内已本地补丁
  067902 dating=illust_dating22（阿奇拉约会皮归属，上游表缺失）；重建元数据后
  若上游更新需重打该补丁。此前缺失时四个 10-22 新服装显示「未知角色」：
  021291=出云天花 Special Date、021391=山城恋 Role Reversal、003793=布莱德
  Tender Dream、004192=提尔 Clumsy Wuff——**新世代「互动皮肤」（联动 Special
  Date 系列）是完整可玩服装**（own battle/Ultimate/互动 spine），不是
  illust_datingN；其 spine 为 idle+motion 结构（槽位 *_touch 触点标记）。
  未命名角色按 id 独立命名的规则不变（build_entry / load_character_fallback /
  build_unknown_entry 三处任一留 "Unknown" 都会重新合并）。
- GalleryView 的 `SPINE_INTERACTIVE` 白名单是碧蓝数据得出的静态清单，BD2 皮肤不在此列时
  互动模式仍可用（点击切表情），仅拖拽提示文案不显示；待改为运行时按骨架动画判定。
- 兼容性保留的旧标识：WE 一键应用副本标记 `.azl2d-marker`（改字节会让旧副本失去可清理性）、
  localStorage 键 `azl_*` 前缀、%APPDATA%rowndust2-wallpaper 用户数据目录——均不影响功能。
