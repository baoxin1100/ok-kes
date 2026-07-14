<div align="center">
  <h1 align="center">
    <img src="icons/icon.png" width="200" alt="ok-kes logo"/>
    <br/>
    ok-kes
  </h1> 
  
  <p>
    一个基于图像识别的卡厄思梦境自动化辅助工具，支持后台运行，基于 <a href="https://github.com/ok-oldking/ok-script">ok-script</a> 开发。
    <br />
    An image-recognition-based automation tool for Chaos Zero Nightmare (卡厄思梦境), with background mode support, developed with <a href="https://github.com/ok-oldking/ok-script">ok-script</a>.
  </p>
  
  <p><i>通过 Windows 接口模拟用户进行操作，无内存读取、无文件修改</i></p>
  <p><b>✅ 支持国际服繁体中文 & 国服 PC 客户端</b></p>
</div>

<!-- Badges -->
<div align="center">
  
![平台](https://img.shields.io/badge/platform-Windows-blue)
[![GitHub release](https://img.shields.io/github/v/release/baoxin1100/ok-kes)](https://github.com/baoxin1100/ok-kes/releases)
[![总下载量](https://img.shields.io/github/downloads/baoxin1100/ok-kes/total)](https://github.com/baoxin1100/ok-kes/releases)
[![Discord](https://img.shields.io/discord/296598043787132928?color=5865f2&label=%20Discord)](https://discord.gg/vVyCatEBgA)

</div>

### [English Readme](README_en.md) | 中文说明

---

## ⚠️ 免责声明

本软件为外部辅助工具，旨在自动化《卡厄思梦境》的部分游戏流程。它完全通过模拟常规用户界面与游戏交互，遵循相关法律法规。本项目旨在简化用户的重复性操作，不会破坏游戏平衡或提供不公平优势，也绝不会修改任何游戏文件或数据。

本软件开源、免费，仅供个人学习与交流使用，请勿用于任何商业或营利性目的。开发者团队拥有本项目的最终解释权。因使用本软件而产生的任何问题，均与本项目及开发者无关。

**使用本软件即表示您已阅读、理解并同意以上声明，并自愿承担一切潜在风险。**

## 🚀 快速开始

1. **下载安装包**：从下方的"下载渠道"中选择一个，下载最新的安装文件。
2. 运行程序：右击以管理员模式运行 `.exe` 文件（无需安装，首次启动会弹出防火墙提示，请允许通过）。

## 📥 下载渠道

* **[GitHub](https://github.com/baoxin1100/ok-kes/releases)**: 官方发布页。（**请下载 `卡厄思自动化工具v*.exe` 文件，而不是 `Source Code` 源码压缩包**）
* **[夸克网盘](https://pan.quark.cn/s/d3f3a7528a81?pwd=Rjbr)**: 国内网盘，免费，但需要注册并使用其客户端下载。
* **[百度网盘](https://pan.baidu.com/s/1MRg_BoLscj2yqf_-m0RAGg?pwd=tcdr)**: 国内网盘，需要注册并使用其客户端下载。

## ✨ 主要功能

<img src="docs/images/image_1.png" alt="功能界面" />

### 自动出击模式
- 🎮 自动战斗：基于按键识别的智能出牌，支持玩家配置出牌优先级
- 🃏 自动选牌：自动获取、移除、复制、闪光卡牌
- ⚔️ 主战员选择：自动按优先级选择出站主战员
- 🛣️ 路线选择：智能识别节点类型，按优先级自动前进
- 🏪 商店处理：自动进入德朗商店移除卡牌
- 💊 以太补充检测：检测体力不足时自动退出
- 支持自定义卡牌优先级、移除/复制/闪光列表等配置

### 自动卡厄思模式
- 🃏 自动卡牌管理：移除、复制、闪光、赋予闪光、转换等
- 🛣️ 路线选择：自动识别休息/事件/boss/小怪节点
- 🏥 精神崩溃治疗：自动前往创伤中心治疗
- 📦 存储数据处理：自动删除存档（可配置保留）
- 🏪 商店处理：自动进入德朗商店
- 🌀 零式系统支持：自动处理法典搜索
- 更多功能持续开发中...

### 半自动剧情模式
- 💬 自动对话：跳过剧情对话
- ⚠️ 遇到战斗或卡厄思关卡时可手动切换对应模式

### 通用功能
- 🖥️ **高分辨率支持**: 支持 1920x1080 / 1600x900 / 1280x720 等 16:9 分辨率
- 🔄 **后台模式**: 支持游戏窗口最小化或被遮挡时在后台运行
- 🌏 **多语言游戏支持**: 支持简体中文、繁体中文客户端（需在软件左下角设置页内将"游戏语言"设置为对应语言）
  <img src="docs/images/image_2.png" alt="国际服游戏语言设置" />

## 🔧 使用说明

1. **国际服玩家必读**：请到软件左下角设置页内将"游戏语言"设置为繁体中文
2. **自动战斗**：依赖按键识别，请在游戏设置中打开快捷键显示，提升出牌准确率
3. **卡厄思模式**：请主动打开游戏内自动战斗和自动剧情功能
4. **剧情模式**：战斗关卡可手动开启出击模式调用自动战斗功能；遇到卡厄思关卡请手动打开卡厄思模式；战斗关卡队伍需手动配置

## 🔧 疑难解答 (Troubleshooting)

如果遇到问题，请在提问前按以下步骤逐一排查：

1. **杀毒软件**：将软件所在目录添加到杀毒软件（包括 Windows Defender）的**信任区或白名单**中，以防文件被误删或拦截。
2. **显示设置**：
   * 关闭所有显卡滤镜（如 NVIDIA Game Filter）和锐化功能。
   * 使用游戏默认的亮度设置。
   * 关闭任何在游戏画面上显示信息的叠加层。
3. **游戏分辨率**：请确保游戏分辨率设置为 16:9 比例。
4. **软件版本**：检查并确保您使用的是最新版本。
5. **寻求帮助**：如果以上步骤都无法解决您的问题，请通过社区渠道提交详细的错误报告。

---

## 💻 开发者专区

### 从源码运行 (Python)

本项目基于 conda 的 `oknikke` 环境（Python 3.12）。

```bash
# 安装或更新依赖
pip install -r requirements.txt --upgrade

# 运行 Release 版本
python main.py

# 运行 Debug 版本
python main_debug.py
```

## 💬 加入我们

- **QQ 交流群**: `462079653` (入群答案: `老王同学OK`)
- **QQ 频道**: [点击加入](https://pd.qq.com/s/djmm6l44y)
- **Discord**: https://discord.gg/vVyCatEBgA

本项目基于 [ok-script](https://github.com/ok-oldking/ok-script) 框架开发，简单易维护。欢迎有兴趣的开发者使用 [ok-script](https://github.com/ok-oldking/ok-script) 开发您自己的自动化项目。

## 🔗 使用ok-script的项目：

* 鸣潮 [https://github.com/ok-oldking/ok-wuthering-wave](https://github.com/ok-oldking/ok-wuthering-waves)
* 原神(停止维护, 但是后台过剧情可用) [https://github.com/ok-oldking/ok-genshin-impact](https://github.com/ok-oldking/ok-genshin-impact)
* 少前2 [https://github.com/ok-oldking/ok-gf2](https://github.com/ok-oldking/ok-gf2)
* 星铁 [https://github.com/Shasnow/ok-starrailassistant](https://github.com/Shasnow/ok-starrailassistant)
* 星痕共鸣 [https://github.com/Sanheiii/ok-star-resonance](https://github.com/Sanheiii/ok-star-resonance)
* 二重螺旋 [https://github.com/BnanZ0/ok-duet-night-abyss](https://github.com/BnanZ0/ok-duet-night-abyss)
* 白荆回廊(停止更新) [https://github.com/ok-oldking/ok-baijing](https://github.com/ok-oldking/ok-baijing)

## ❤️ 致谢

* [ok-script](https://github.com/ok-oldking/ok-script)
* [OnnxOCR](https://github.com/ok-oldking/OnnxOCR)
* [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)