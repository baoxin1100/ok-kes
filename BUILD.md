# 打包指南

## 前置条件

本项目的打包环境为 conda 的 `oknikke` 环境（Python 3.12），使用该环境的 python 和 pip 执行打包命令。

```bash
pip install -r requirements.txt
pip install pyinstaller
```

## 打包步骤

### 1. 内联依赖

将 ok-script 和 pyappify 运行时库内联到项目中：

```bash
python -m ok.update.inline_ok_requirements
```

### 2. 执行 PyInstaller 打包

```bash
pyinstaller --onefile --noconsole --uac-admin --noupx --runtime-tmpdir "C:\Temp\ok_kes" --name "卡厄思自动化工具v1.2.5" --icon icons/icon.ico ^
  --add-data assets;assets ^
  --add-data i18n;i18n ^
  --add-data ok_tasks;ok_tasks ^
  --add-data "C:\Users\baoxin\miniconda3\envs\oknikke\Lib\site-packages\opencc\clib;opencc\clib" ^
  --add-data "C:\Users\baoxin\miniconda3\envs\oknikke\Lib\site-packages\opencc\clib\share\opencc;opencc\lib\share\opencc" ^
  --hidden-import ok_tasks.SortieMode ^
  --hidden-import ok_tasks.ChaosMode ^
  --hidden-import utils_sortie ^
  --hidden-import utils_chaos ^
  --hidden-import src.globals ^
  --hidden-import src.tasks.MyOneTimeTask ^
  --hidden-import onnxocr ^
  --hidden-import onnxocr_ppocrv5 ^
  --exclude-module PySide6.translations ^
  --collect-all onnxocr ^
  --collect-all openvino ^
  --collect-all pyappify ^
  main.py
```

### 3. 清理临时文件

```bash
rmdir /s /q build
del "卡厄思自动化工具v1.2.2.spec"
```

### 4. 产物

位于 `dist\卡厄思自动化工具v1.2.2.exe`，约 265 MB。

## 关键说明

> **⚠️ 注意**：`build_exe.bat` 必须使用 **GBK/ANSI 编码**保存，CMD 才能正确解析中文文件名。如果用 UTF-8 编码，打包出来的 exe 名称会显示为乱码。

| 参数 | 作用 |
|---|---|
| `--onefile` | 单文件 exe，用户下载即用 |
| `--noconsole` | 无控制台窗口 |
| `--uac-admin` | 请求管理员权限 |
| `--add-data ok_tasks;ok_tasks` | 打包任务文件，运行时通过 `os.chdir(sys._MEIPASS)` 找到 |
| `--hidden-import src.globals` | 动态引用的全局对象模块 |
| `--collect-all openvino` | 包含 OpenVINO 完整库（否则缺少 ONNX 前端导致模型加载失败） |
| `--collect-all onnxocr` | 包含 OCR 模型文件（.onnx）和代码 |
| `--runtime-tmpdir` | 指定纯英文临时解压路径，避免中文用户名导致 OpenCC C 库 fopen 失败 |
| `--add-data opencc\clib;opencc\clib` | 打包 OpenCC 绑定的动态库和字典文件 |
| `--add-data opencc\lib\share\opencc` | 额外映射字典目录到 lib 路径，解决中文路径下 C 库查找 `t2s.json` 失败 |
| `--exclude-module PySide6.translations` | 排除 PySide6 翻译文件（.qm），避免某些系统上解压 CRC 校验失败 |

## 代码层面的必要修改

打包前需要确保以下修改已存在：

### `main.py`
```python
import sys
import os

if __name__ == '__main__':
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        os.chdir(sys._MEIPASS)  # 切换到临时解压目录，使 ok_tasks 等数据文件可被找到
        config["config_folder"] = os.path.join(exe_dir, "configs")  # 配置文件保存在 exe 目录下，避免被临时目录清除
```

### `ok/gui/MainWindow.py`
- 顶部添加 `import sys`

### `ok/gui/tasks/TaskManger.py`
`find_and_instantiate_class` 方法添加编码回退逻辑，解决 GBK/ANSI 编码文件导致 `utf-8' codec can't decode byte` 报错：
```python
def find_and_instantiate_class(self, file_path, base_class):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            tree = ast.parse(file.read(), filename=file_path)
    except UnicodeDecodeError:
        with open(file_path, 'r', encoding=sys.getfilesystemencoding()) as file:
            tree = ast.parse(file.read(), filename=file_path)
```
