"""预设卡组编辑器（实验模式配置里的“编辑预设卡组”按钮）。

界面刻意保持简单：一个列表 + 添加/编辑/复制/删除/排序及两种导入入口。
一条记录代表一张卡，需要两张就复制一条。
"""
import copy
import threading

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from preset_deck import _normalize_record, convert_legacy_flash_priority
from preset_deck_import import DeckImportError, convert_preset, decode_share_code, validate_code


_IMPORT_WORKERS = set()


class _DeckImportWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    completed = Signal()

    def __init__(self, code, language):
        super().__init__()
        self.code = code
        self.language = language
        self.cancelled = threading.Event()
        self.completed.connect(self._dispose)

    def start(self):
        _IMPORT_WORKERS.add(self)
        # A daemon thread lets the application close during a pending request.
        # All widget changes are delivered through queued Qt signals.
        threading.Thread(target=self._run, daemon=True, name="preset-deck-import").start()

    def _run(self):
        try:
            preset = decode_share_code(self.code)
            if not self.cancelled.is_set():
                result = convert_preset(preset, self.language)
                if not self.cancelled.is_set():
                    self.succeeded.emit(result)
        except DeckImportError as exc:
            if not self.cancelled.is_set():
                self.failed.emit(str(exc))
        except Exception:
            if not self.cancelled.is_set():
                self.failed.emit("卡组数据格式无法识别，导入未完成，原预设已保留。")
        finally:
            self.completed.emit()

    @Slot()
    def _dispose(self):
        _IMPORT_WORKERS.discard(self)
        self.deleteLater()


class DeckCodeImportDialog(QDialog):
    """Decode first; the caller only replaces records after Accepted."""

    def __init__(self, language, parent=None):
        super().__init__(parent)
        self.language = language
        self.result_data = None
        self.worker = None
        self._cancelled = False
        self.setWindowTitle("从卡组码导入")
        self.resize(570, 310)
        layout = QVBoxLayout(self)
        hint = QLabel(
            f"导入文本语言：{language}（取自本模式的「游戏语言」配置）。\n"
            "成功后覆盖当前窗口的全部预设卡牌，点击主窗口「保存」后生效。\n"
            "能识别的字段会尽量导入，缺失字段在表格「导入提示」列标出，可双击补填。\n"
            "联网解析会将卡组码发送到 cznmetadecks.com；部分卡组码可能暂不受支持。\n"
            "含【记忆】等赛季卡的卡组码可能无法解析。若解析失败，请先在原 BD 中去掉赛季卡，"
            "重新导出卡组码后再导入。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.code_edit = QPlainTextEdit()
        self.code_edit.setPlaceholderText("在此粘贴完整的官方卡组码（v6l7… 或 v6l8…）")
        layout.addWidget(self.code_edit, 1)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("取消")
        self.import_button = QPushButton("导入并覆盖")
        self.import_button.setDefault(True)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.import_button)
        layout.addLayout(buttons)
        self.cancel_button.clicked.connect(self.reject)
        self.import_button.clicked.connect(self._start_import)

    def _start_import(self):
        if self.worker is not None:
            return
        try:
            code = validate_code(self.code_edit.toPlainText())
        except DeckImportError as exc:
            self.status_label.setText(str(exc))
            return
        self._cancelled = False
        self.code_edit.setEnabled(False)
        self.import_button.setEnabled(False)
        self.status_label.setText("正在联网解析卡组码，请稍候…")
        self.worker = _DeckImportWorker(code, self.language)
        self.worker.succeeded.connect(self._succeeded)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    @Slot(object)
    def _succeeded(self, result):
        if self._cancelled:
            return
        self.result_data = result
        self.accept()

    @Slot(str)
    def _failed(self, message):
        if self._cancelled:
            return
        self.worker = None
        self.code_edit.setEnabled(True)
        self.import_button.setEnabled(True)
        self.status_label.setText(message)

    def reject(self):
        self._cancelled = True
        if self.worker is not None:
            self.worker.cancelled.set()
        super().reject()

    def closeEvent(self, event):
        self.reject()
        event.accept()


def _bump_font(widget, delta=2):
    """把控件字号整体加大两号。"""
    font = widget.font()
    if font.pointSize() > 0:
        font.setPointSize(font.pointSize() + delta)
    else:
        pixel_size = font.pixelSize()
        font.setPixelSize((pixel_size if pixel_size > 0 else 12) + delta)
    widget.setFont(font)
    return font


def _mm_to_px(mm):
    """按主屏幕逻辑 DPI 把毫米换算成行高像素。"""
    try:
        screen = QApplication.primaryScreen()
        dpi = screen.logicalDotsPerInch() if screen is not None else 96.0
    except Exception:
        dpi = 96.0
    if not dpi or dpi <= 0:
        dpi = 96.0
    return max(1, round(float(mm) / 25.4 * dpi))


def _record_divine_display(record):
    texts = record.get("divine_text", []) or []
    text = "；".join(texts) if texts else "不判断"
    if record.get("reject_divine"):
        text += "（拒绝神闪）"
    return text


class PresetCardDialog(QDialog):
    """单张预设卡的添加/编辑窗口。"""

    def __init__(self, parent=None, record=None):
        super().__init__(parent)
        _bump_font(self)
        self.setWindowTitle("编辑预设卡牌")
        self.resize(480, 540)
        self.record = copy.deepcopy(record) if record else {
            "name": "",
            "effects": [],
            "divine_text": [],
            "reject_divine": False,
        }

        layout = QVBoxLayout(self)
        if self.record.get("import_notes"):
            notes_label = QLabel("导入待补充：\n" + "\n".join(self.record["import_notes"]) + "\n编辑后点击「确定」将清除此卡的导入提示。")
            notes_label.setWordWrap(True)
            layout.addWidget(notes_label)
        layout.addWidget(QLabel("卡牌名（必填，填卡面上能认出的名字即可）"))
        self.name_edit = QLineEdit(str(self.record.get("name", "")))
        self.name_edit.setPlaceholderText("例如：光之剑路")
        layout.addWidget(self.name_edit)

        layout.addWidget(QLabel("卡牌效果（一行一个关键字，任意一行命中即可）"))
        self.effect_edit = QPlainTextEdit()
        self.effect_edit.setPlaceholderText("例如：造成360%的伤害\n本回合叠加凝聚")
        self.effect_edit.setPlainText("\n".join(self.record.get("effects", []) or []))
        layout.addWidget(self.effect_edit, 1)

        layout.addWidget(QLabel("神闪效果（神闪图标后面那行文本，一行一个关键字）"))
        self.divine_edit = QPlainTextEdit()
        self.divine_edit.setPlaceholderText("例如：此卡牌费用减少1\n生成2张剑穗")
        self.divine_edit.setPlainText("\n".join(self.record.get("divine_text", []) or []))
        layout.addWidget(self.divine_edit, 1)

        self.reject_check = QCheckBox("拒绝神闪（这张卡出现神闪形态时不选它）")
        self.reject_check.setChecked(bool(self.record.get("reject_divine")))
        layout.addWidget(self.reject_check)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("取消")
        self.ok_button = QPushButton("确定")
        self.ok_button.setDefault(True)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.ok_button)
        layout.addLayout(buttons)

        self.cancel_button.clicked.connect(self.reject)
        self.ok_button.clicked.connect(self._accept)

    def _accept(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "卡牌名不能为空")
            return
        self.record = {
            "name": name,
            "effects": [
                line.strip()
                for line in self.effect_edit.toPlainText().splitlines()
                if line.strip()
            ],
            "divine_text": [
                line.strip()
                for line in self.divine_edit.toPlainText().splitlines()
                if line.strip()
            ],
            "reject_divine": self.reject_check.isChecked(),
        }
        self.accept()


class PresetDeckDialog(QDialog):
    """预设卡组列表窗口。"""

    def __init__(self, task, parent=None):
        super().__init__(parent)
        _bump_font(self)
        self.task = task
        config = getattr(task, "config", None)
        raw = config.get("预设卡组", []) if isinstance(config, dict) else []
        if isinstance(raw, list):
            self.records = [
                record for record in (_normalize_record(item) for item in raw) if record
            ]
        else:
            self.records = []
        self.setWindowTitle("预设卡组")
        self.resize(980, 620)

        layout = QVBoxLayout(self)
        title = QLabel(
            "预设卡组（从上到下匹配；一条记录 = 一张卡，需要多张请用「复制」）\n"
            "匹配顺序：卡牌名 → 卡牌效果 → 神闪效果；神闪形态可以在编辑里单独拒绝。"
        )
        title.setWordWrap(True)
        title.setFont(self.font())
        layout.addWidget(title)

        self.table = QTableWidget(0, 5, self)
        self.table.setFont(self.font())
        self.table_item_font = self.font()
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(
            self.table.fontMetrics().height() + 8 + _mm_to_px(0.5)
        )
        self.table.setHorizontalHeaderLabels(["顺序", "卡牌名", "卡牌效果", "神闪效果", "导入提示"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setFont(self.font())
        header.setMinimumHeight(self.table.fontMetrics().height() + 14)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        self.table.setColumnWidth(4, 180)
        self.table.doubleClicked.connect(lambda _: self._edit())
        layout.addWidget(self.table, 1)

        toolbar = QHBoxLayout()
        for text, handler in (
            ("添加", self._add),
            ("编辑", self._edit),
            ("复制", self._copy),
            ("删除", self._delete),
            ("上移", self._move_up),
            ("下移", self._move_down),
            ("从闪光优先级导入", self._import_legacy),
            ("从卡组码导入", self._import_code),
        ):
            button = QPushButton(text)
            button.setFont(self.font())
            button.clicked.connect(handler)
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setFont(self.font())
        self.save_button = QPushButton("保存")
        self.save_button.setFont(self.font())
        self.save_button.setDefault(True)
        bottom.addWidget(self.cancel_button)
        bottom.addWidget(self.save_button)
        layout.addLayout(bottom)

        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._save)

        self._refresh()

    # ------------------------------------------------------------------
    def _refresh(self, select_row=None):
        self.table.setRowCount(0)
        for index, record in enumerate(self.records, 1):
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = (
                str(index),
                str(record.get("name", "")),
                "；".join(record.get("effects", []) or []),
                _record_divine_display(record),
                "；".join(record.get("import_notes", []) or []),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFont(self.table_item_font)
                item.setData(Qt.UserRole, record)
                item.setToolTip(value)
                if column == 4 and value:
                    item.setForeground(QColor("#b36b00"))
                self.table.setItem(row, column, item)
        if self.records:
            row = select_row if select_row is not None else 0
            row = max(0, min(row, len(self.records) - 1))
            self.table.selectRow(row)

    def _selected_row(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.records):
            return None
        return row

    def _insert_record(self, record, row):
        row = max(0, min(row, len(self.records)))
        self.records.insert(row, record)
        self._refresh(row)

    # ------------------------------------------------------------------
    def _add(self):
        dialog = PresetCardDialog(self)
        if dialog.exec() == QDialog.Accepted:
            row = self._selected_row()
            self._insert_record(dialog.record, len(self.records) if row is None else row + 1)

    def _edit(self):
        row = self._selected_row()
        if row is None:
            return
        dialog = PresetCardDialog(self, self.records[row])
        if dialog.exec() == QDialog.Accepted:
            self.records[row] = dialog.record
            self._refresh(row)

    def _copy(self):
        row = self._selected_row()
        if row is None:
            return
        self._insert_record(copy.deepcopy(self.records[row]), row + 1)

    def _delete(self):
        row = self._selected_row()
        if row is None:
            return
        del self.records[row]
        self._refresh(min(row, len(self.records) - 1))

    def _move_up(self):
        row = self._selected_row()
        if row is None or row <= 0:
            return
        self.records[row - 1], self.records[row] = self.records[row], self.records[row - 1]
        self._refresh(row - 1)

    def _move_down(self):
        row = self._selected_row()
        if row is None or row >= len(self.records) - 1:
            return
        self.records[row + 1], self.records[row] = self.records[row], self.records[row + 1]
        self._refresh(row + 1)

    def _import_legacy(self):
        try:
            from ok.util.config import Config
            from ok.util.file import get_relative_path, read_json_file

            path = get_relative_path(Config.config_folder, "ChaosMode.json")
            data = read_json_file(path) or {}
            legacy = data.get("闪光优先级", []) if isinstance(data, dict) else []
        except Exception:
            legacy = []
        if not legacy and hasattr(self.task, "config"):
            legacy = self.task.config.get("闪光优先级", [])
        records = convert_legacy_flash_priority(legacy)
        if not records:
            QMessageBox.information(self, "提示", "没有找到可导入的闪光优先级配置")
            return
        self.records.extend(records)
        self._refresh(len(self.records) - len(records))
        QMessageBox.information(
            self,
            "提示",
            f"已导入 {len(records)} 条记录。\n"
            "旧配置是“名称+描述”的合并文本，请检查卡牌名和效果关键字是否符合预期。",
        )

    def _import_code(self):
        language = self.task.config.get("游戏语言", "简体中文")
        dialog = DeckCodeImportDialog(language, self)
        if dialog.exec() != QDialog.Accepted or dialog.result_data is None:
            return
        records, warnings, character = dialog.result_data
        self.records = records
        self._refresh(0)
        text = f"已覆盖为{('「' + character + '」') if character else ''}卡组，共 {len(records)} 张卡。\n点击「保存」写入配置，点击「取消」放弃本次修改。"
        if warnings:
            count = sum(bool(record.get("import_notes")) for record in records)
            text += f"\n\n已保留可识别的数据，{count} 张卡有字段需要补充。\n查看表格「导入提示」列，双击对应卡牌编辑。\n跳过的异常记录等信息可展开「详细信息」查看。"
            message = QMessageBox(QMessageBox.Information, "导入完成，请检查", text, QMessageBox.Ok, self)
            message.setDetailedText("\n".join(warnings))
            message.exec()
        else:
            QMessageBox.information(self, "导入完成", text)

    def _save(self):
        for record in self.records:
            if not str(record.get("name", "")).strip():
                QMessageBox.warning(self, "提示", "有记录没有填写卡牌名，保存失败")
                return
        self.accept()


def open_preset_deck_editor(task):
    """在配置按钮回调里打开编辑器；保存后写回任务配置。"""
    parent = None
    try:
        from ok import og
        parent = getattr(og, "main_window", None)
    except Exception:
        parent = None
    dialog = PresetDeckDialog(task, parent)
    if dialog.exec() != QDialog.Accepted:
        return
    task.config["预设卡组"] = dialog.records
    try:
        from config_io import refresh_task_config_widgets
        refresh_task_config_widgets(task)
    except Exception:
        pass
