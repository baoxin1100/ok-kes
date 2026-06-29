# 打包指南

## 前置条件

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
pyinstaller --onefile --noconsole --uac-admin --name ok-script-app ^
  --add-data assets;assets ^
  --add-data i18n;i18n ^
  --add-data ok_tasks;ok_tasks ^
  --hidden-import ok_tasks.SortieMode ^
  --hidden-import ok_tasks.ChaosMode ^
  --hidden-import utils_sortie ^
  --hidden-import utils_chaos ^
  --hidden-import src.globals ^
  --hidden-import src.tasks.MyOneTimeTask ^
  --hidden-import onnxocr ^
  --hidden-import onnxocr_ppocrv5 ^
  --collect-all onnxocr ^
  --collect-all openvino ^
  --collect-all pyappify ^
  main.py
```

### 3. 清理临时文件

```bash
rmdir /s /q build dist\ok-script-app
del ok-script-app.spec _build.py build_log.txt
```

### 4. 产物

位于 `dist\ok-script-app.exe`，约 265 MB。

## 关键说明

| 参数 | 作用 |
|---|---|
| `--onefile` | 单文件 exe，用户下载即用 |
| `--noconsole` | 无控制台窗口 |
| `--uac-admin` | 请求管理员权限 |
| `--add-data ok_tasks;ok_tasks` | 打包任务文件，运行时通过 `os.chdir(sys._MEIPASS)` 找到 |
| `--hidden-import src.globals` | 动态引用的全局对象模块 |
| `--collect-all openvino` | 包含 OpenVINO 完整库（否则缺少 ONNX 前端导致模型加载失败） |
| `--collect-all onnxocr` | 包含 OCR 模型文件（.onnx）和代码 |

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
