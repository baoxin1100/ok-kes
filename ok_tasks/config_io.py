import base64
import json
import os

from ok import og
from ok.util.config import Config
from ok.util.file import get_relative_path, read_json_file, write_json_file


LOCAL_CONFIG_PROFILES_FILE = "local_config_profiles.json"
UI_ONLY_CONFIG_KEYS = {"配置操作"}


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


def migrate_game_language_config_file(task):
    """将旧版全局游戏语言迁移到当前模式配置，仅执行一次。"""
    config_file = get_relative_path(
        Config.config_folder,
        f"{task.__class__.__name__}.json",
    )
    data = read_json_file(config_file)
    if not isinstance(data, dict):
        data = {}
    if "游戏语言" in data:
        return

    legacy_config_file = get_relative_path(Config.config_folder, "游戏语言.json")
    legacy_data = read_json_file(legacy_config_file)
    game_language = "简体中文"
    if isinstance(legacy_data, dict):
        legacy_language = legacy_data.get("游戏语言")
        if legacy_language in {"简体中文", "繁体中文"}:
            game_language = legacy_language
    data["游戏语言"] = game_language
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
    clean = {
        k: v
        for k, v in data.items()
        if not k.startswith('_') and k not in UI_ONLY_CONFIG_KEYS
    }
    if "游戏语言" in getattr(task, "default_config", {}):
        clean["游戏语言"] = task.config.get(
            "游戏语言",
            task.default_config["游戏语言"],
        )
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
        if key not in allowed_config or key in UI_ONLY_CONFIG_KEYS:
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
            if (key.startswith('_') or key in allowed_config)
            and key not in UI_ONLY_CONFIG_KEYS
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


def _local_profiles_file():
    """返回独立于任务配置文件的本地方案存储路径。"""
    return get_relative_path(Config.config_folder, LOCAL_CONFIG_PROFILES_FILE)


def _read_local_profiles(task):
    """读取全部本地配置方案；文件损坏时返回空结构。"""
    data = read_json_file(_local_profiles_file())
    if isinstance(data, dict):
        return data
    if data is not None:
        task.log_info("本地配置方案文件格式无效，将按空方案处理")
    return {}


def _write_local_profiles(task, data):
    """写入全部本地配置方案。"""
    try:
        write_json_file(_local_profiles_file(), data)
        return True
    except Exception as exc:
        task.log_info(f"写入本地配置方案失败: {exc}")
        return False


def _current_config_snapshot(task):
    """保存当前模式全部有效配置，不包含框架内部字段。"""
    snapshot = {}
    for key, default_value in getattr(task, "default_config", {}).items():
        if key.startswith("_") or key in UI_ONLY_CONFIG_KEYS:
            continue
        value = task.config.get(key, default_value)
        # 配置均为 JSON 类型，通过序列化生成独立副本，避免列表被后续修改。
        snapshot[key] = json.loads(json.dumps(value, ensure_ascii=False))
    return snapshot


def _game_language(task):
    """获取用户当前选择的游戏语言。"""
    try:
        return str(task.config.get("游戏语言", "简体中文")).strip() or "简体中文"
    except Exception:
        return "简体中文"


def _app_version():
    """获取当前程序版本，用于生成默认方案名称。"""
    try:
        configured_version = (og.config or {}).get("version")
        if configured_version:
            return str(configured_version).strip()
    except Exception:
        pass
    try:
        from src.config import version
        return str(version).strip() or "dev"
    except Exception:
        return "dev"


def _default_local_profile_name(task, mode):
    """按模式、主战员、语言和版本生成默认方案名称。"""
    if mode == "chaos":
        member_name = str(task.config.get("刷存档主战员", "")).strip()
    else:
        members = task.config.get("出战主战员优先级", [])
        member_name = str(members[0]).strip() if isinstance(members, list) and members else ""
    member_name = member_name or "未指定主战员"
    return f"{member_name}-{_game_language(task)}-{_app_version()}"


def _apply_local_profile(task, profile):
    """复用导入配置的校验、落盘和缓存刷新逻辑加载本地方案。"""
    encoded = base64.b64encode(
        json.dumps(profile, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return _import_config_from_text(task, encoded)


def make_save_local_config_callback(task, mode):
    """生成保存本地配置方案按钮的回调函数。"""
    def save_local_config():
        from PySide6.QtWidgets import QInputDialog, QMessageBox

        default_name = _default_local_profile_name(task, mode)
        proposed_name = default_name
        while True:
            entered_name, accepted = QInputDialog.getText(
                None,
                "保存配置",
                "请输入本地配置名称：",
                text=proposed_name,
            )
            if not accepted:
                return
            profile_name = entered_name.strip() or default_name

            all_profiles = _read_local_profiles(task)
            mode_profiles = all_profiles.get(mode)
            if not isinstance(mode_profiles, dict):
                mode_profiles = {}

            if profile_name in mode_profiles:
                reply = QMessageBox.question(
                    None,
                    "配置名称重复",
                    f"本地配置“{profile_name}”已存在。\n\n"
                    "选择“是”覆盖原配置，选择“否”重新命名。",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                    QMessageBox.No,
                )
                if reply == QMessageBox.Cancel:
                    return
                if reply == QMessageBox.No:
                    proposed_name = profile_name
                    continue

            mode_profiles[profile_name] = _current_config_snapshot(task)
            all_profiles[mode] = mode_profiles
            if _write_local_profiles(task, all_profiles):
                QMessageBox.information(
                    None,
                    "保存成功",
                    f"当前配置已保存为“{profile_name}”。",
                )
                task.log_info(f"本地配置保存成功: {profile_name}")
            else:
                QMessageBox.warning(None, "保存失败", "本地配置文件写入失败。")
            return

    return save_local_config


def make_switch_local_config_callback(task, mode):
    """生成加载和删除本地配置方案按钮的回调函数。"""
    def switch_local_config():
        from PySide6.QtWidgets import (
            QDialog,
            QHBoxLayout,
            QListWidget,
            QListWidgetItem,
            QMessageBox,
            QPushButton,
            QVBoxLayout,
        )

        dialog = QDialog()
        dialog.setWindowTitle("切换配置")
        dialog.resize(480, 360)
        layout = QVBoxLayout(dialog)
        profile_list = QListWidget()
        layout.addWidget(profile_list)

        button_layout = QHBoxLayout()
        load_button = QPushButton("加载所选配置")
        delete_button = QPushButton("删除所选配置")
        cancel_button = QPushButton("取消")
        load_button.setEnabled(False)
        delete_button.setEnabled(False)
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(delete_button)
        button_layout.addWidget(load_button)
        layout.addLayout(button_layout)

        def reload_profile_list():
            profile_list.clear()
            mode_profiles = _read_local_profiles(task).get(mode, {})
            if not isinstance(mode_profiles, dict):
                return
            for profile_name in mode_profiles:
                profile_list.addItem(QListWidgetItem(profile_name))

        def selected_profile_name():
            selected_items = profile_list.selectedItems()
            return selected_items[0].text() if selected_items else ""

        def update_button_state():
            has_selection = bool(selected_profile_name())
            load_button.setEnabled(has_selection)
            delete_button.setEnabled(has_selection)

        def load_selected_profile():
            profile_name = selected_profile_name()
            if not profile_name:
                return
            mode_profiles = _read_local_profiles(task).get(mode, {})
            profile = mode_profiles.get(profile_name) if isinstance(mode_profiles, dict) else None
            if not isinstance(profile, dict):
                QMessageBox.warning(dialog, "加载失败", "所选本地配置不存在或格式无效。")
                reload_profile_list()
                return
            if _apply_local_profile(task, profile):
                refresh_task_config_widgets(task)
                QMessageBox.information(dialog, "加载成功", f"已加载“{profile_name}”。")
                task.log_info(f"本地配置加载成功: {profile_name}")
                dialog.accept()
            else:
                QMessageBox.warning(dialog, "加载失败", "本地配置写入失败。")

        def delete_selected_profile():
            profile_name = selected_profile_name()
            if not profile_name:
                return
            reply = QMessageBox.question(
                dialog,
                "确认删除",
                f"确定删除本地配置“{profile_name}”吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            all_profiles = _read_local_profiles(task)
            mode_profiles = all_profiles.get(mode, {})
            if isinstance(mode_profiles, dict):
                mode_profiles.pop(profile_name, None)
                all_profiles[mode] = mode_profiles
            if _write_local_profiles(task, all_profiles):
                task.log_info(f"已删除本地配置: {profile_name}")
                reload_profile_list()
                update_button_state()
            else:
                QMessageBox.warning(dialog, "删除失败", "本地配置文件写入失败。")

        profile_list.itemSelectionChanged.connect(update_button_state)
        profile_list.itemDoubleClicked.connect(lambda _item: load_selected_profile())
        load_button.clicked.connect(load_selected_profile)
        delete_button.clicked.connect(delete_selected_profile)
        cancel_button.clicked.connect(dialog.reject)
        reload_profile_list()
        dialog.exec_()

    return switch_local_config
