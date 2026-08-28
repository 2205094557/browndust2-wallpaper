# Brown Dust 2 立绘壁纸工坊

棕色尘埃2（Brown Dust 2）国际服立绘提取工具。从官方 CDN 下载并提取 **Spine 4.1 动态立绘**（主立绘 / Fated Guest 约会 / 尊爵 / Ultimate 技能演出）、**静态立绘** 与 **互动语音**，在图鉴式 Web 界面中预览，然后导出为 Wallpaper Engine 壁纸项目。

> 由 [azurlane-dynamic-wallpaper](https://github.com/your-username/azurlane-dynamic-wallpaper)（碧蓝航线动态壁纸工具）复刻改造而来，碧蓝遗留代码已全部清理，仅保留其插件化架构。

## 功能特性

- **四类动态内容**：主立绘（`charXXXXXX`）/ 约会立绘（`illust_datingN`）/ 尊爵立绘 / Ultimate 技能演出（`cutscene_charXXXXXX`），全部 Spine 4.1
  - Ultimate 演出自动提取独立背景图（正方形场景），在角色背后渲染，支持独立缩放
- **静态立绘**（`illust_charXXXXXX_NNN`）直接导出大图
- **互动语音**：官方 FEV+FSB5 语音包 → FSB5 切片 → vgmstream 解码为 wav，点击角色播放情绪语音
- **BD2 拟官方互动系统**：点击角色触发整段演出（mix 序列），连续点击立即切换下一段，原生 160ms 交叉淡化过渡
- 官方 CDN 目录（Addressables catalog）按需下载 + AssetBundle 本地解包提取
- 图鉴式 Web 预览（背景样式含取色、莫奈、毛玻璃、星空等；独立背景缩放滑块）
- 导出 Wallpaper Engine 壁纸项目（project.json 原生属性 + 一键应用）
- 角色缩放与背景缩放独立控制，16:9 预览舞台
- **四套主题**：水彩画风（默认）/ 少女漫画风 / 赛博朋克 / 太阳朋克

## 快速开始

```bash
# 开发栈（后端 8766 + Vite 5173 + 桌面窗口）
python scripts/start_dev.py
```

或双击根目录 `start_dev.bat`（自动检测 Python，无需手动配置 .venv）。

首次使用：图鉴中选择角色 → 下载 → 预览 → 导出/应用。

## 技术要点（详见 AGENTS.md）

- 版本：`PUT mt.bd2.pmang.cloud/MaintenanceInfo`（protobuf 解析）
- 目录：`cdn.bd2.pmang.cloud/ServerData/Android/{HD|SD}/{version}/catalog_alpha.json`（AssetBundle Addressables 格式）
- 主立绘/约会/尊爵为全角色共享大包（86MB/434MB/438MB），一次下载全角色复用
- UnityPy 解包需 `FALLBACK_UNITY_VERSION=2022.3.22f1`（新版 bundle 版本头被抹除）
- BD2 贴图为直通 alpha，渲染时上传预乘（`BD2_PREMULTIPLY_UPLOAD=true`）
- 互动引擎单源文件 `templates/shared/bd2-interact.js`，预览与壁纸模板共用
- 互动模式：`mix` 风格（第二代约会）走官方顺序播放序列，每段演出 ~160ms 交叉淡化

## 项目结构

```
├── frontend/            # Vue 3 前端（Vite）
│   └── src/
│       ├── components/  # SpinePreview.vue（预览引擎 + 互动系统）
│       └── features/    # GalleryView（图鉴）、PreviewView（预览页）
├── templates/           # 壁纸模板 + 运行时
│   ├── wallpaper_spine.html  # 导出壁纸的 HTML 模板
│   ├── shared/bd2-interact.js # BD2 互动引擎（单源文件）
│   └── spine41/         # spine-webgl 4.1 运行时
├── plugins/             # 插件体系
│   ├── sources/         # CDN 数据源（BD2 协议）
│   ├── extractors/      # Spine/静态提取器
│   └── exporters/       # Wallpaper Engine 导出器
├── core/                # 核心库（元数据、资源库、取色、壁纸配置）
├── tools/               # 元数据构建、CDN 自检、端到端测试
└── scripts/             # 开发/打包脚本
```

## 资源仅供个人学习交流使用