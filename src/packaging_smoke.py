"""Read-only frozen application self-test; never starts game automation."""
import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--self-test-report", required=True, type=Path)
    args = parser.parse_args()
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)), "checks": []}
    try:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        sys.path.insert(0, str(root / "ok_tasks"))
        from PySide6.QtWidgets import QApplication, QPushButton
        from opencc import OpenCC
        app = QApplication.instance() or QApplication([])
        assert OpenCC("t2s").convert("劍之共鳴") == "剑之共鸣"
        report["checks"].append("OpenCC 字典与本地动态库")
        from ChaosModeExperimental import ChaosModeExperimental
        from preset_deck_ui import PresetDeckDialog
        from preset_deck_import import load_catalog
        task = ChaosModeExperimental(SimpleNamespace(scene=None), None)
        task.config = {"预设卡组": [], "游戏语言": "繁体中文"}
        dialog = PresetDeckDialog(task)
        assert "从卡组码导入" in [button.text() for button in dialog.findChildren(QPushButton)]
        assert len(load_catalog()["cards"]) > 2000
        dialog.close()
        report["checks"].append("实验任务、预设编辑器和中文卡牌映射")
        from src.window_recovery import install_window_recovery
        install_window_recovery()
        from src.config import version
        report["version"] = version
        from src.globals import Globals
        assert Globals is not None
        assert (root / "icons" / "icon.png").is_file()
        assert (root / "ok_tasks" / "assets" / "coco_annotations.json").is_file()
        assert (root / "docs" / "images" / "wechat_reward_code.png").is_file()
        report["checks"].append("动态导入和界面资源")
        import numpy as np
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr
        engine = ONNXPaddleOcr(use_openvino=False)
        result = engine.ocr(np.full((96, 256, 3), 255, dtype=np.uint8))
        assert isinstance(result, list)
        report["checks"].append("ONNX Runtime 与 OCR 模型实际推理")
        report["ok"] = True
        app.processEvents()
    except Exception:
        report["error"] = traceback.format_exc()
    args.self_test_report.parent.mkdir(parents=True, exist_ok=True)
    args.self_test_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
