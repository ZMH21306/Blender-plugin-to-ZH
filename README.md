# Blender 插件汉化合集

> 精选 Blender 插件的简体中文汉化版本合集

[![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)
[![Blender](https://img.shields.io/badge/Blender-3.0+-orange?style=flat-square&logo=blender)](https://www.blender.org/)

---

## 📖 项目简介

**Blender 插件汉化合集** 是一个精选 Blender 插件的简体中文汉化版本集合。每个插件均提供原始版本（`_ZH` 后缀为汉化版）和汉化版本，方便中文用户使用。所有插件均以 `.zip` 形式提供，可直接通过 Blender 的「安装插件」功能导入。

## 📦 插件列表

| 插件 | 版本 | 说明 | 汉化版 |
|------|------|------|--------|
| [BlenderMCP](Blender-mcp/) | — | 通过 MCP 协议连接 Claude AI，实现 AI 辅助 3D 建模 | ✅ `Blender-mcp_ZH` |
| [BlenderGIS](BlenderGIS_GIS数据文件导入_v2.2.15/) | v2.2.15 | GIS 数据文件导入 | ✅ `BlenderGIS_ZH.zip` |
| [Blenderkit](Blenderkit_3D素材库_v3.21.0.260628/) | v3.21.0 | 3D 素材库 | ✅ `Blenderkit_ZH.zip` |
| [Blosm](Blosm_真实地形数据_v2.7.27/) | v2.7.27 | 真实地形数据 | ✅ `Blosm_ZH.zip` |
| [Quicksnap](Quicksnap_快速吸附_v1.5.1/) | v1.5.1 | 快速吸附 | ✅ `Quicksnap_ZH.zip` |
| [Step-importer](Step-importer_STEP文件导入_v1.2.1/) | v1.2.1 | STEP 文件导入 | ✅ `Step-importer_ZH.zip` |
| [Super-io](Super-io_万能导入导出_v2.2.1/) | v2.2.1 | 万能导入导出 | ✅ `Super-io_ZH.zip` |

## 🗂️ 项目结构

```
Blender-plugin-to-ZH/
├── Blender-mcp/                    # BlenderMCP 插件（含源码）
│   ├── blender-mcp/                # 原始英文版
│   ├── Blender-mcp_ZH/             # 简体中文汉化版
│   └── 安装提示.txt                 # 安装提示
├── BlenderGIS_GIS数据文件导入_v2.2.15/
│   ├── BlenderGIS.zip              # 原始版
│   └── BlenderGIS_ZH.zip           # 汉化版
├── Blenderkit_3D素材库_v3.21.0.260628/
│   ├── Blenderkit.zip              # 原始版
│   └── Blenderkit_ZH.zip           # 汉化版
├── Blosm_真实地形数据_v2.7.27/
│   ├── Blosm.zip                   # 原始版
│   └── Blosm_ZH.zip                # 汉化版
├── Quicksnap_快速吸附_v1.5.1/
│   ├── Quicksnap.zip               # 原始版
│   └── Quicksnap_ZH.zip            # 汉化版
├── Step-importer_STEP文件导入_v1.2.1/
│   ├── Step-importe.zip            # 原始版
│   └── Step-importer_ZH.zip        # 汉化版
├── Super-io_万能导入导出_v2.2.1/
│   ├── Super-io.zip                # 原始版
│   └── Super-io_ZH.zip             # 汉化版
├── LICENSE
└── README.md
```

## 🚀 安装方法

### 方法一：通过 Blender 界面安装（推荐）

1. 打开 Blender，进入 **编辑（Edit）→ 偏好设置（Preferences）→ 插件（Add-ons）**
2. 点击 **安装（Install...）** 按钮
3. 选择对应的 `_ZH.zip` 汉化包文件
4. 在插件列表中勾选启用该插件

### 方法二：手动复制

1. 解压 `_ZH.zip` 文件
2. 将解压后的文件夹复制到 Blender 的插件目录：
   - **Windows**: `%APPDATA%\Blender Foundation\Blender\<版本>\scripts\addons\`
   - **macOS**: `~/Library/Application Support/Blender/<版本>/scripts/addons/`
   - **Linux**: `~/.config/blender/<版本>/scripts/addons/`
3. 重启 Blender，在插件列表中启用

### BlenderMCP 特殊说明

BlenderMCP 插件需要额外的 Python 环境配置，详见 [Blender-mcp 安装说明](Blender-mcp/blender-mcp/README.md)。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建功能分支（`feature/描述`）
3. 提交更改
4. 推送到分支
5. 提交 Pull Request

## 📄 许可证

本项目基于 **MIT** 许可证分发。详见 [LICENSE](LICENSE) 文件。

> **注意**：各插件本身遵循其原始许可证，汉化版仅对界面文本进行翻译，不改变原始功能与许可证。
