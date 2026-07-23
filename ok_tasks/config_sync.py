"""
配置同步模块：Supabase 匿名上传/下载热门配置

功能：
1. 每5分钟自动上传匿名配置 + 胜率到 Supabase
2. 获取热门配置列表（按胜率或使用人数排序）
3. 应用热门配置到本地

不上传任何个人信息，仅上传：
- 配置的 base64 编码
- 胜率统计数据
- 配置版本号
- 匿名用户标识（机器特征的哈希）
"""
import os
import hashlib
import platform
import uuid

import requests
from ok import TriggerTask
from config_io import _import_config_from_text, _export_config_to_text

# Supabase 配置
SUPABASE_URL = "https://curzwmogotwmltaprmin.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_9Kn7mcglnMHGPEkJbxZhuA_erescsdk"
TABLE_NAME = "configs"

# 上传间隔（秒）
UPLOAD_INTERVAL = 300  # 5分钟

# 有效数据最低场数（后期用户多了可以改大）
MIN_ROUNDS = 5


def _get_version():
    """从 src/config.py 读取当前版本号。"""
    try:
        from src.config import version
        return version
    except Exception:
        return "dev"


def _get_user_hash() -> str:
    """生成匿名用户标识：基于机器特征的一次性哈希。
    
    组合 MAC 地址、主机名、用户名，取 SHA256 的前 16 位作为用户标识。
    每次启动后缓存，保证同一台机器标识不变。
    """
    if not hasattr(_get_user_hash, '_cache'):
        try:
            import subprocess
            result = subprocess.run(['getmac'], capture_output=True, text=True, shell=True)
            mac_line = result.stdout.split('\n')[0] if result.stdout else ''
            mac = mac_line.split()[0] if mac_line else str(uuid.getnode())
        except Exception:
            mac = str(uuid.getnode())
        raw = f"{mac}|{platform.node()}|{os.environ.get('USERNAME', 'unknown')}"
        _get_user_hash._cache = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return _get_user_hash._cache


def _get_win_rate(task: TriggerTask) -> float:
    """从 task.node_status 读取当前胜率。"""
    ns = getattr(task, 'node_status', None)
    if not ns:
        return 0.0
    total = ns.get('total_rounds', 0)
    success = ns.get('success_rounds', 0)
    if total < MIN_ROUNDS:
        return -1.0  # 数据不足
    return success / total if total > 0 else 0.0


def _should_upload(task: TriggerTask) -> bool:
    """检查是否满足上传条件：
    1. 全局配置"是否上传配置"为 True
    2. 有足够的战斗场数
    """
    try:
        lang_config = task.executor.global_config.get_config('配置上传')
        enabled = lang_config.get('是否上传配置', True)
    except Exception:
        enabled = True
    win_rate = _get_win_rate(task)
    if win_rate < 0:
        task.log_debug(f"[配置同步] 数据不足{MIN_ROUNDS}场，跳过上传")
        return False
    return bool(enabled)


def upload_config(task: TriggerTask, mode: str) -> bool:
    """上传当前配置到 Supabase。
    
    Args:
        task: TriggerTask 实例
        mode: "chaos" 或 "sortie"
    
    Returns:
        bool: 是否上传成功
    """
    if not _should_upload(task):
        return False

    config_b64 = _export_config_to_text(task)
    if not config_b64:
        return False

    win_rate = _get_win_rate(task)
    if win_rate < 0:
        return False

    ns = getattr(task, 'node_status', {})
    total_rounds = ns.get('total_rounds', 0)

    user_hash = _get_user_hash()
    config_ver = _get_version()

    # 读取当前游戏语言
    game_lang = "简体中文"
    try:
        lang_config = task.executor.global_config.get_config('游戏语言')
        game_lang = lang_config.get('游戏语言', '简体中文')
    except Exception:
        pass

    # 读取出战主战员优先级第一个名字（仅在出击模式有效）
    first_member = ""
    if mode == "sortie":
        try:
            member_list = task.config.get('出战主战员优先级', [])
            if isinstance(member_list, (list, tuple)) and len(member_list) > 0:
                first_member = member_list[0]
        except Exception:
            pass

    payload = {
        "mode": mode,
        "config_b64": config_b64,
        "config_ver": config_ver,
        "game_lang": game_lang,
        "first_member": first_member,
        "win_rate": round(win_rate, 4),
        "total_rounds": total_rounds,
        "user_hash": user_hash,
    }

    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
            json=payload,
            headers=headers,
            timeout=10,
        )
        if resp.status_code in (200, 201, 204):
            task.log_debug(f"[配置同步] 上传成功 (mode={mode}, win_rate={win_rate:.1%})")
            return True
        else:
            task.log_info(f"[配置同步] 上传失败: HTTP {resp.status_code} {resp.text[:200]}")
            return False
    except requests.RequestException as e:
        task.log_info(f"[配置同步] 上传异常: {e}")
        return False


def fetch_popular_configs(
    mode: str,
    sort_by: str = "winrate",
    limit: int = 20,
    version: str = None,
) -> list:
    """从 Supabase 获取热门配置列表。
    
    Args:
        mode: "chaos" 或 "sortie"
        sort_by: "winrate"（按平均胜率降序）或 "users"（按使用人数降序）
        limit: 返回条数
        version: 可选，过滤配置版本
    
    Returns:
        list[dict]: 每个元素包含 config_b64, avg_win_rate, user_count 等
    """
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    }

    # 先获取足够多的原始数据
    params = {
        "select": "config_b64,config_ver,game_lang,first_member,win_rate,total_rounds,user_hash",
        "mode": f"eq.{mode}",
        "total_rounds": f"gte.{MIN_ROUNDS}",
        "order": "win_rate.desc",
        "limit": 200,  # 获取 200 条，足够客户端聚合
    }
    if version:
        params["config_ver"] = f"eq.{version}"

    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
            headers=headers,
            params=params,
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        records = resp.json()
    except requests.RequestException:
        return []

    if not records:
        return []

    # 按 config_b64 聚合
    groups = {}
    for r in records:
        key = r["config_b64"]
        if key not in groups:
            groups[key] = {
                "config_b64": key,
                "config_ver": r.get("config_ver", "unknown"),
                "game_lang": r.get("game_lang", "简体中文"),
                "first_member": r.get("first_member", ""),
                "win_rates": [],
                "users": set(),
            }
        groups[key]["win_rates"].append(r["win_rate"])
        groups[key]["users"].add(r["user_hash"])

    # 计算聚合结果
    result = []
    for key, g in groups.items():
        user_count = len(g["users"])
        if user_count < 1:
            continue
        result.append({
            "config_b64": g["config_b64"],
            "config_ver": g["config_ver"],
            "game_lang": g["game_lang"],
            "first_member": g["first_member"],
            "avg_win_rate": round(sum(g["win_rates"]) / len(g["win_rates"]), 4),
            "user_count": user_count,
            "total_submissions": len(g["win_rates"]),
        })

    # 排序
    if sort_by == "users":
        result.sort(key=lambda x: (-x["user_count"], -x["avg_win_rate"]))
    else:  # winrate
        result.sort(key=lambda x: (-x["avg_win_rate"], -x["user_count"]))

    # 去掉重复的 config_b64（同一个配置被不同版本上传）
    seen = set()
    unique_result = []
    for r in result:
        if r["config_b64"] not in seen:
            seen.add(r["config_b64"])
            unique_result.append(r)

    return unique_result[:limit]


def check_upload_disabled_and_warn(task: TriggerTask) -> bool:
    """检查配置上传是否已关闭，若关闭则弹窗提示并返回 True。"""
    try:
        lang_config = task.executor.global_config.get_config('配置上传')
        upload_enabled = lang_config.get('是否上传配置', True)
    except Exception:
        upload_enabled = True
    if not upload_enabled:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(
            None, "热门配置不可用",
            "请先在左下角设置页中开启「配置上传」功能，才能使用热门配置。\n\n"
            "开启后，您可以浏览和下载其他高胜率玩家分享的配置。"
        )
        return True
    return False


def check_upload_if_needed(task: TriggerTask, mode: str):
    """每 UPLOAD_INTERVAL 秒自动上传一次配置。"""
    import time
    now = time.time()
    if now - getattr(task, '_last_upload_time', 0) >= UPLOAD_INTERVAL:
        task._last_upload_time = now
        upload_config(task, mode)


def show_hot_configs_dialog(task: TriggerTask, mode: str):
    """弹出热门配置选择对话框。
    
    Args:
        task: TriggerTask 实例
        mode: "chaos" 或 "sortie"
    """
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
        QListWidgetItem, QPushButton, QMessageBox, QComboBox, QApplication,
    )
    from PySide6.QtCore import Qt

    if check_upload_disabled_and_warn(task):
        return

    mode_name = "卡厄思模式" if mode == "chaos" else "出击模式"
    dialog = QDialog()
    dialog.setWindowTitle(f"热门配置 - {mode_name}")
    dialog.resize(650, 500)

    layout = QVBoxLayout(dialog)

    # 筛选行：排序方式 + 出战主战员筛选
    filter_layout = QHBoxLayout()
    sort_label = QLabel("排序方式：")
    sort_combo = QComboBox()
    sort_combo.addItem("按胜率降序", "winrate")
    sort_combo.addItem("按使用人数降序", "users")
    filter_layout.addWidget(sort_label)
    filter_layout.addWidget(sort_combo)

    # 出战主战员筛选（出击模式可用）
    member_filter_combo = None
    if mode == "sortie":
        member_filter_label = QLabel("出战主战员：")
        member_filter_combo = QComboBox()
        member_filter_combo.addItem("不限", "")
        filter_layout.addWidget(member_filter_label)
        filter_layout.addWidget(member_filter_combo)

    filter_layout.addStretch()
    layout.addLayout(filter_layout)

    # 加载提示
    loading_label = QLabel("正在加载热门配置，请稍候...")
    loading_label.setStyleSheet("color: gray; padding: 20px;")
    loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(loading_label)

    # 列表
    config_list = QListWidget()
    config_list.setVisible(False)
    layout.addWidget(config_list)

    # 按钮
    btn_layout = QHBoxLayout()
    refresh_btn = QPushButton("刷新")
    apply_btn = QPushButton("应用所选配置")
    apply_btn.setEnabled(False)
    cancel_btn = QPushButton("取消")
    btn_layout.addWidget(refresh_btn)
    btn_layout.addStretch()
    btn_layout.addWidget(apply_btn)
    btn_layout.addWidget(cancel_btn)
    layout.addLayout(btn_layout)

    # 缓存所有结果
    all_results = []

    def load_configs():
        nonlocal all_results
        sort_by = sort_combo.currentData()
        all_results = fetch_popular_configs(mode=mode, sort_by=sort_by, limit=200)
        # 更新成员筛选下拉框选项
        if member_filter_combo is not None:
            current_member = member_filter_combo.currentData() or ""
            member_filter_combo.blockSignals(True)
            member_filter_combo.clear()
            member_filter_combo.addItem("不限", "")
            members = sorted(set(r.get("first_member", "") for r in all_results if r.get("first_member")))
            for m in members:
                member_filter_combo.addItem(m, m)
            # 恢复之前选择的筛选项
            idx = member_filter_combo.findData(current_member)
            if idx >= 0:
                member_filter_combo.setCurrentIndex(idx)
            member_filter_combo.blockSignals(False)
        apply_member_filter()

    def apply_member_filter():
        selected_member = member_filter_combo.currentData() if member_filter_combo else ""
        filtered = all_results
        if selected_member:
            filtered = [r for r in filtered if r.get("first_member", "") == selected_member]
        config_list.clear()
        loading_label.setVisible(False)
        if not filtered:
            item = QListWidgetItem("暂无热门配置数据（至少需要5场有效数据才会被统计）")
            config_list.addItem(item)
            return
        for i, r in enumerate(filtered[:20], 1):
            wr = r["avg_win_rate"]
            uc = r["user_count"]
            ver = r.get("config_ver", "?")
            gl = r.get("game_lang", "简体中文")
            fm = r.get("first_member", "")
            if fm:
                text = f"#{i}  胜率: {wr:.0%}  使用人数: {uc}  主战员: {fm}  语言: {gl}  版本: {ver}"
            else:
                text = f"#{i}  胜率: {wr:.0%}  使用人数: {uc}  语言: {gl}  版本: {ver}"
            item = QListWidgetItem(text)
            item.setData(0x100, r)  # 36 = Qt.UserRole
            config_list.addItem(item)

    def on_filter_changed():
        loading_label.setVisible(True)
        config_list.setVisible(False)
        apply_member_filter()
        config_list.setVisible(True)

    def on_apply():
        selected = config_list.selectedItems()
        if not selected:
            return
        r = selected[0].data(0x100)
        if not r:
            return
        reply = QMessageBox.question(
            dialog, "确认应用",
            f"将应用所选配置（胜率: {r['avg_win_rate']:.0%}, 使用人数: {r['user_count']}）\n当前配置将被覆盖。\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            success = _import_config_from_text(task, r["config_b64"])
            if success:
                QMessageBox.information(dialog, "导入成功", "热门配置已成功应用！")
                dialog.accept()
            else:
                QMessageBox.warning(dialog, "导入失败", "配置解析失败，请重试。")

    # 绑定事件
    sort_combo.currentIndexChanged.connect(on_filter_changed)
    if member_filter_combo is not None:
        member_filter_combo.currentIndexChanged.connect(on_filter_changed)
    config_list.itemSelectionChanged.connect(lambda: apply_btn.setEnabled(len(config_list.selectedItems()) > 0))
    refresh_btn.clicked.connect(on_filter_changed)
    apply_btn.clicked.connect(on_apply)
    cancel_btn.clicked.connect(dialog.reject)

    # 初始加载
    loading_label.setVisible(True)
    load_configs()
    config_list.setVisible(True)
    loading_label.setVisible(False)

    dialog.exec_()
