"""Build a Windows portable exe from a clean source staging directory."""
import argparse
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="实验包使用基础版本，例如 v1.4.9")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("请在 Windows x64 和 Python 3.12 环境中打包")
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-(?:alpha|beta)\.\d+)?", args.version):
        parser.error("版本号格式错误")
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="portable-src-", dir=build))
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.backup_*")
    for name in ("src", "ok_tasks", "icons", "i18n"):
        shutil.copytree(ROOT / name, stage / name, ignore=ignore)
    (stage / "docs").mkdir()
    shutil.copytree(ROOT / "docs" / "images", stage / "docs" / "images", ignore=ignore)
    shutil.copy2(ROOT / "main.py", stage / "main.py")
    # Version only the staging copy; source builds continue to display dev.
    config_file = stage / "src" / "config.py"
    config, count = re.subn(r'^version = "[^"]+"', f'version = "{args.version}"',
                            config_file.read_text(encoding="utf-8"), count=1, flags=re.M)
    if count != 1:
        raise RuntimeError("未找到源码版本字段，停止打包")
    config_file.write_text(config, encoding="utf-8")
    name = f"ok-kes-experimental-win64-{args.version}"
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
               "--uac-admin", "--noupx", "--runtime-tmpdir", "C:/Temp/ok-kes",
               "--name", name, "--icon", str(stage / "icons" / "icon.ico"),
               "--distpath", str(ROOT / "dist"), "--workpath", str(build / name),
               "--specpath", str(build / "spec"), "--paths", str(stage),
               "--paths", str(stage / "ok_tasks")]
    for directory in ("ok_tasks", "icons", "i18n", "docs/images"):
        command += ["--add-data", f"{stage / directory}{os.pathsep}{directory}"]
    for package in ("ok", "pyappify", "onnxocr", "onnxruntime", "opencc", "openvino"):
        command += ["--collect-all", package]
    # The framework discovers these tasks by name from configuration/AST.
    for module in ("src.globals", "src.tasks.MyOneTimeTask", "src.packaging_smoke",
                   "ChaosMode", "ChaosModeExperimental", "SortieMode", "StoryMode",
                   "preset_deck", "preset_deck_ui", "preset_deck_import", "config_io",
                   "config_sync", "utils", "utils_chaos", "utils_sortie", "win32timezone"):
        command += ["--hidden-import", module]
    # OpenCC's native library also searches this alternate dictionary location.
    opencc = Path(importlib.util.find_spec("opencc").origin).parent
    command += ["--add-data", f"{opencc / 'clib' / 'share' / 'opencc'}{os.pathsep}opencc/lib/share/opencc",
                "--exclude-module", "PySide6.translations", str(stage / "main.py")]
    print("源码暂存目录:", stage, flush=True)
    subprocess.run(command, cwd=stage, check=True)
    artifact = ROOT / "dist" / f"{name}.exe"
    digest = hashlib.file_digest(artifact.open("rb"), "sha256").hexdigest()
    (ROOT / "dist" / "SHA256SUMS.txt").write_text(f"{digest}  {artifact.name}\n", encoding="ascii")
    print("打包完成:", artifact, "大小:", artifact.stat().st_size, "SHA256:", digest)


if __name__ == "__main__":
    main()
