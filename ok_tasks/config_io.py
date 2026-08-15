import base64
import json
import os

from ok import og
from ok.util.config import Config
from ok.util.file import get_relative_path, read_json_file, write_json_file


def refresh_task_config_widgets(task):
    """原位刷新任务卡片的配置控件，不删除或重建任务卡片。"""
    main_window = getattr(og, "main_window", None)
    trigger_tab = getattr(main_window, "trigger_tab", None)
    if trigger_tab is None:
        return

    for task_card in getattr(trigger_tab, "card_widgets", []):
        if getattr(task_card, "task", None) is not task:
            continue
        for widget in getattr(task_card, "config_widgets", []):
            update_value = getattr(widget, "update_value", None)
            if callable(update_value):
                update_value()
        apply_visibility = getattr(
            task_card,
            "_ConfigContentMixin__apply_sub_config_visibility",
            None,
        )
        if callable(apply_visibility):
            apply_visibility()
        adjust_size = getattr(task_card, "_adjust_config_content_size", None)
        if callable(adjust_size):
            adjust_size()
        break


def _migrate_flash_priority(data):
    """将旧版闪光优先级 JSON 字符串转换为按顺序匹配的列表。"""
    value = data.get("闪光优先级")
    if not isinstance(value, str):
        return data
    try:
        old_priority = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        data["闪光优先级"] = []
        return data
    if not isinstance(old_priority, dict):
        data["闪光优先级"] = []
        return data
    data["闪光优先级"] = [
        f"{card_name}：{description}"
        for card_name, descriptions in old_priority.items()
        if isinstance(card_name, str)
        for description in (
            descriptions if isinstance(descriptions, (list, tuple)) else []
        )
        if isinstance(description, str) and description
    ]
    return data


def migrate_flash_priority_config_file(task):
    """在框架按默认值校验类型前迁移本地旧版配置文件。"""
    config_file = get_relative_path(
        Config.config_folder,
        f"{task.__class__.__name__}.json",
    )
    data = read_json_file(config_file)
    if not isinstance(data, dict) or not isinstance(data.get("闪光优先级"), str):
        return
    _migrate_flash_priority(data)
    write_json_file(config_file, data)


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
    _migrate_flash_priority(data)

    # 旧版分享配置可能包含当前版本已经删除的字段。ConfigCard 会根据
    # default_config 判断控件类型，废弃字段没有默认值，会被解析为 None。
    allowed_config = getattr(task, "default_config", {})
    ignored_keys = []
    sanitized_data = {}
    for key, value in data.items():
        if key not in allowed_config:
            ignored_keys.append(key)
            continue
        default_value = allowed_config[key]
        if type(value) is not type(default_value):
            ignored_keys.append(key)
            continue
        sanitized_data[key] = value
    if ignored_keys:
        task.log_info(f"导入配置时忽略无效或已废弃字段: {', '.join(ignored_keys)}")
    data = sanitized_data

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
        existing = {
            key: value
            for key, value in existing.items()
            if key.startswith('_') or key in allowed_config
        }
        for k, v in data.items():
            existing[k] = v
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        # 刷新 task.config 缓存
        for key in list(task.config):
            if not key.startswith('_') and key not in allowed_config:
                dict.pop(task.config, key, None)
        task.config.update(data)
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
            refresh_task_config_widgets(task)
        else:
            QMessageBox.warning(None, "导入失败", "编码无效或写入失败，请检查后重试。")
    return import_config
