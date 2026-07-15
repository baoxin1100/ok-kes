import base64
import json
import os

from ok import og
from ok.gui.Communicate import communicate


def _export_config_to_text(task):
    """将任务的用户配置导出为 base64 编码文本。"""
    config_file = task.config.config_file
    if not os.path.exists(config_file):
        task.log_info("配置文件不存在，无法导出")
        return None
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        task.log_info(f"读取配置文件失败: {e}")
        return None
    # 只保留用户配置项（去掉 _ 开头的内部状态）
    clean = {k: v for k, v in data.items() if not k.startswith('_')}
    json_str = json.dumps(clean, ensure_ascii=False, separators=(',', ':'))
    encoded = base64.b64encode(json_str.encode('utf-8')).decode('ascii')
    return encoded


def _import_config_from_text(task, encoded_text):
    """从 base64 编码文本导入配置到任务配置文件。"""
    try:
        json_str = base64.b64decode(encoded_text.encode('ascii')).decode('utf-8')
        data = json.loads(json_str)
    except Exception as e:
        task.log_info(f"解码失败，无效的配置编码: {e}")
        return False
    if not isinstance(data, dict):
        task.log_info("无效的配置数据格式")
        return False
    # 写入配置文件
    config_file = task.config.config_file
    try:
        # 合并：保留 _ 开头的内部状态，覆盖用户配置
        existing = {}
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except Exception:
                pass
        for k, v in data.items():
            existing[k] = v
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        # 刷新 task.config 缓存
        task.config.update(data)
        # 触发 UI 刷新
        communicate.task_list_updated.emit()
        return True
    except Exception as e:
        task.log_info(f"写入配置文件失败: {e}")
        return False


def make_export_callback(task):
    """生成导出配置按钮的回调函数。"""
    def export():
        from PySide6.QtWidgets import QMessageBox, QApplication
        encoded = _export_config_to_text(task)
        if encoded is None:
            QMessageBox.warning(None, "导出失败", "配置文件不存在或读取失败")
            return
        # 复制到剪贴板
        QApplication.clipboard().setText(encoded)
        QMessageBox.information(
            None, "导出成功",
            "配置已复制到剪贴板，可以粘贴发送给其他人。\n\n"
            f"（编码长度: {len(encoded)} 字符）"
        )
        task.log_info(f"配置导出成功，共 {len(encoded)} 字符")
    return export


def make_import_callback(task):
    """生成导入配置按钮的回调函数。"""
    def import_config():
        from PySide6.QtWidgets import QInputDialog, QMessageBox, QApplication
        # 尝试从剪贴板预填文本
        clipboard_text = QApplication.clipboard().text()
        text, ok = QInputDialog.getMultiLineText(
            None, "导入配置", "请粘贴别人分享的配置编码：",
            clipboard_text if clipboard_text else ""
        )
        if not ok or not text.strip():
            return
        text = text.strip()
        success = _import_config_from_text(task, text)
        if success:
            QMessageBox.information(None, "导入成功", "配置已成功导入并应用！")
            task.log_info("配置导入成功")
        else:
            QMessageBox.warning(None, "导入失败", "编码无效或写入失败，请检查后重试。")
    return import_config