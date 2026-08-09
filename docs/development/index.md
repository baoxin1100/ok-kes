# 开发指南

## 环境

项目使用 Python 3.12，维护时使用 Miniconda 的 `oknikke` 环境。

```powershell
conda activate oknikke
python -m pip install -r requirements.txt --upgrade
python main_debug.py
```

## 测试

```powershell
.\run_tests.ps1
```

也可以运行指定的 unittest 测试模块：

```powershell
python -m unittest tests.TestMain
```

## 文档网站

安装文档依赖并启动本地预览：

```powershell
python -m pip install -r requirements-docs.txt
python -m mkdocs serve
```

执行严格构建：

```powershell
python -m mkdocs build --strict
```

HTML 文件生成在 `site/` 目录。推送涉及文档的修改到 `master` 后，GitHub Actions 会构建并发布 GitHub Pages。

## 构建应用

当前正式版本通过 GitHub Actions 构建。具体的历史打包说明保存在仓库根目录的 [`BUILD.md`](https://github.com/baoxin1100/ok-kes/blob/master/BUILD.md)。

## 项目设计

任务模块、配置同步、页面处理器和运行环境说明见[软件需求与设计](../srd.md)。

## 提交修改

- 保持提交范围清晰，不要混入日志、缓存、个人配置或无关生成文件。
- 修改识别逻辑时说明适用页面、识别区域、阈值和测试素材。
- 修改用户可见行为时补充截图、日志或清晰的复现步骤。
- 提交 PR 前运行相关测试，并在 PR 描述中写明结果。
