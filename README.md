## ok-py

[English](README_en.md) | 中文

ok-py 是一个基于 [ok-script](https://github.com/ok-oldking/ok-script) 的 Python 自动化项目模板。它提供了可直接运行的 GUI、任务示例、配置控件示例、OCR 示例、模板匹配示例、测试用例和打包配置，适合用来快速创建自己的 Windows 自动化脚本项目。

这个仓库不是某个具体游戏的自动化成品，而是 ok-script 应用的起步工程和功能演示。

### 功能演示

**API 列表与脚本录制**

![image_scripting](docs/images/image_scripting.png)

**多种截图与交互方式**

![image_screenshot](docs/images/image_capture.png)

**标注管理与模板匹配**

![image_template](docs/images/image_template.png)
![image_markup](docs/images/image_markup.png)

## 主要内容

- 可直接启动的 ok-script GUI 应用入口。
- `MyOneTimeTask` 示例任务，演示常用任务 API 和配置控件。
- 配置控件示例：下拉框、布尔值、整数、浮点数、字符串、多行文本、列表、多选、文件选择、文件夹选择、全局配置和按钮组。
- OCR、相对区域识别和模板匹配示例。
- `ConfigOption` 全局配置示例。
- `TaskTestCase` 自动化测试示例。
- i18n 翻译文件和 `.mo` 编译产物。
- `pyappify.yml` 和 GitHub Actions 打包发布配置。

## 快速开始

本项目建议使用 Python 3.12。Windows 自动化通常需要管理员权限运行终端、PyCharm 或 VS Code。

```bash
pip install -r requirements.txt --upgrade
python main_debug.py
```

运行普通模式：

```bash
python main.py
```

运行测试：

```bash
python -m unittest tests.TestMain
```

## 项目结构

```text
src/tasks              任务类示例
src/config.py          ok-script 应用配置
src/ui                 自定义 UI Tab 示例
tests                  自动化测试用例
assets                 模板匹配资源和 COCO 标注
docs/images            README 使用的演示图片
i18n                   翻译文件
icons                  应用图标
main.py                普通入口
main_debug.py          Debug 入口
pyappify.yml           打包配置
deploy.txt             发布时同步到更新仓库的文件列表
.github/workflows      自动化构建与发布流程
```

## 开发任务

主要示例任务位于 `src/tasks/MyOneTimeTask.py`。你可以从这里开始：

- 修改 `default_config` 增加任务配置默认值。
- 修改 `config_type` 选择配置控件类型。
- 在 `run()` 中编写自动化逻辑。
- 使用 `self.ocr()` 做文字识别。
- 使用 `self.find_one()` 或 `self.find_feature()` 做模板匹配。
- 使用 `self.info_set()` 在 UI 中展示任务状态。
- 使用 `self.log_info(..., notify=True)` 发送通知。

启用自定义任务后，也可以在 GUI 中创建和编辑任务脚本。

## 打包与发布

仓库包含 GitHub Actions 配置。推送符合规则的 tag 后会触发构建：

```text
v*.*.*
```

构建流程会根据 `pyappify.yml` 打包应用，并按 `deploy.txt` 同步更新仓库需要的文件。

## ok-script 文档

- [游戏自动化入门](https://github.com/ok-oldking/ok-script/blob/master/docs/intro_to_automation/README.md)
- [快速开始](https://github.com/ok-oldking/ok-script/blob/master/docs/quick_start/README.md)
- [进阶使用](https://github.com/ok-oldking/ok-script/blob/master/docs/after_quick_start/README.md)
- [API 文档](https://github.com/ok-oldking/ok-script/blob/master/docs/api_doc/README.md)

## 社区

- 用户群：`1097603920`
- 开发者群：`938132715`
- Discord：https://discord.gg/vVyCatEBgA

## 致谢

- [ok-script](https://github.com/ok-oldking/ok-script)
- [OnnxOCR](https://github.com/ok-oldking/OnnxOCR)
- [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)
