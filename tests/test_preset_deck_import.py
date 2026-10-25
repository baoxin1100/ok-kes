import copy
import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ok_tasks"))

from PySide6.QtWidgets import QApplication, QDialog, QPushButton

import preset_deck_import as importer
import preset_deck_ui as ui


SAMPLE = json.loads((ROOT / "tests/fixtures/ross_preset.json").read_text(encoding="utf-8"))
PRESET = {"charId": SAMPLE["character_id"], "cards": SAMPLE["entries"]}
NEW_PRESETS = json.loads((ROOT / "tests/fixtures/mika_lida_presets.json").read_text(encoding="utf-8"))


def response(value, status=200):
    result = Mock(status_code=status)
    result.iter_content.return_value = [value.encode("utf-8")]
    return result


class ImportConversionTests(unittest.TestCase):
    def test_confirmed_deck_preserves_count_variants_and_divine(self):
        original = copy.deepcopy(PRESET)
        records, warnings, name = importer.convert_preset(PRESET, "繁体中文")
        self.assertEqual(name, "羅斯薇瑟")
        self.assertEqual(len(records), 8)  # 11 wire records minus 3 removed.
        self.assertEqual([r["name"] for r in records].count("劍之共鳴"), 4)
        self.assertEqual(records[1], records[2])
        self.assertEqual(records[2], records[3])
        self.assertNotEqual(records[1]["effects"], records[4]["effects"])
        self.assertEqual(records[1]["divine_text"], ["此卡牌費用減少1"])
        self.assertEqual(records[0]["divine_text"], ["此卡牌的傷害量增加30%"])
        self.assertFalse(any(r["reject_divine"] for r in records))
        self.assertEqual(PRESET, original)
        self.assertEqual(warnings, [])
        self.assertNotRegex(json.dumps(records, ensure_ascii=False), r"#[^#]+#|\^[^\^]+\^")

    def test_simplified_uses_task_locale_for_every_field(self):
        records, _, name = importer.convert_preset(PRESET, "简体中文")
        self.assertEqual(name, "罗斯薇瑟")
        self.assertEqual(records[1]["name"], "剑之共鸣")
        self.assertEqual(records[4]["effects"], ["触发手牌中所有明、暗卡牌效果"])
        self.assertEqual(records[0]["divine_text"], ["此卡牌的伤害量增加30%"])

    def test_unknown_fields_preserve_other_cards_and_usable_fields(self):
        original_records = importer.convert_preset(PRESET)[0]
        for field in ["variantCardId", "divineId", "epiphanyId"]:
            preset = copy.deepcopy(PRESET)
            preset["cards"][-1][field] = "unknown_id"
            with self.subTest(field=field):
                records, warnings, _ = importer.convert_preset(preset)
                self.assertEqual(len(records), 8)
                self.assertEqual(records[:-1], original_records[:-1])
                self.assertEqual(records[-1]["name"], original_records[-1]["name"])
                self.assertTrue(records[-1]["import_notes"])
                self.assertTrue(warnings)
                if field == "variantCardId":
                    self.assertEqual(records[-1]["effects"], [])
                else:
                    self.assertEqual(records[-1]["effects"], original_records[-1]["effects"])
                self.assertNotIn("unknown_id", str(records[-1]["effects"] + records[-1]["divine_text"]))

    def test_invalid_records_and_empty_active_deck(self):
        for preset in [{"cards": []}, {"cards": [None]}, {"cards": [{"removed": "false"}]},
                       {"cards": [{"cardId": []}]}, {"cards": [{"removed": True}]}]:
            with self.subTest(preset=preset), self.assertRaises(importer.DeckImportError):
                importer.convert_preset(preset)

    def test_unsupported_language_is_explicit(self):
        with self.assertRaises(importer.DeckImportError):
            importer.convert_preset(PRESET, "English")

    def test_real_mika_short_divine_and_general_epiphany(self):
        for language in ("简体中文", "繁体中文"):
            with self.subTest(language=language):
                records, warnings, _ = importer.convert_preset(NEW_PRESETS["mika"], language)
                self.assertEqual(len(records), 7)
                self.assertEqual([r["name"] for r in records].count("水之根源"), 4)
                self.assertEqual([r["divine_text"] for r in records[:4]], [["抽取1"]] * 3 + [[]])
                self.assertEqual(records[4]["effects"], ["水波2"])
                self.assertEqual(records[-1]["effects"], ["不屈1"])
                # The healing percentage is dynamic and cannot distinguish all
                # 作战分析 variants with the remaining static text alone.
                self.assertEqual(len(warnings), 1)
                self.assertIn("区分", records[4]["import_notes"][0])

    def test_real_lida_general_epiphanies_preserve_copies_and_locale(self):
        original = copy.deepcopy(NEW_PRESETS["lida"])
        for language, name, effect in [("简体中文", "破坏时间轴", "持续1回合，获得士气3"),
                                        ("繁体中文", "破壞時間軸", "持續1回合，獲得士氣3")]:
            with self.subTest(language=language):
                records, warnings, _ = importer.convert_preset(original, language)
                self.assertEqual(len(records), 11)
                self.assertEqual([r["name"] for r in records[1:4]], [name] * 3)
                self.assertEqual([r["effects"] for r in records[1:4]], [[effect]] * 3)
                morale = "士气" if language == "简体中文" else "士氣"
                self.assertEqual([r["name"] for r in records[5:9]], ["急救包"] * 4)
                self.assertEqual([r["effects"] for r in records[5:]],
                                 [[morale + "2"]] * 4 + [[morale + "1"], [morale + "2"]])
                self.assertEqual(warnings, [])
        self.assertEqual(original, NEW_PRESETS["lida"])

    def test_mixed_bad_records_do_not_discard_valid_or_unknown_named_rows(self):
        active = next(copy.deepcopy(e) for e in PRESET["cards"] if not e.get("removed"))
        preset = {"cards": [None, active, {"cardId": "new_card"},
                            {"cardId": [], "variantCardId": active["cardId"]},
                            {"cardId": active["cardId"], "variantCardId": []},
                            {"cardId": active["cardId"], "epiphanyId": [], "divineId": ["invalid"]},
                            {"removed": "false"}, {"removed": True}]}
        records, warnings, _ = importer.convert_preset(preset)
        self.assertEqual(len(records), 5)
        self.assertEqual(records[0], importer.convert_preset({"cards": [active]})[0][0])
        self.assertIn("未识别卡牌", records[1]["name"])
        self.assertEqual(records[1]["effects"], [])
        self.assertIn("import_notes", records[1])
        self.assertTrue(any("已跳过" in note for note in warnings))
        self.assertTrue(any("神闪" in note for note in records[-1]["import_notes"]))

    def test_variant_and_extra_epiphany_are_not_written_as_alternatives(self):
        preset = copy.deepcopy(NEW_PRESETS["mika"])
        active = next(e for e in preset["cards"] if not e.get("removed"))
        baseline = importer.convert_preset(preset)[0][0]["effects"]
        active["epiphanyId"] = "c03012"
        records, warnings, _ = importer.convert_preset(preset)
        self.assertEqual(records[0]["effects"], baseline)
        self.assertTrue(warnings)
        self.assertTrue(any("附加灵光" in note for note in records[0]["import_notes"]))

    def test_ambiguous_dynamic_variant_warns(self):
        catalog = {"characters": {}, "divine": {}, "cards": {
            "c_1_srt1": {"name": "劍", "text": "造成#damage#的傷害"},
            "c_1_srt1_rsp1": {"name": "劍", "text": "造成#damage#的傷害"}}}
        records, warnings, _ = importer.convert_preset({"cards": [
            {"cardId": "c_1_srt1", "variantCardId": "c_1_srt1_rsp1"}]}, catalog=catalog)
        self.assertEqual(len(records), 1)
        self.assertTrue(warnings)

    def test_unresolved_markup_is_not_written_to_ocr_keywords(self):
        self.assertEqual(importer._keywords("手牌中有此卡牌時士氣#1減少1\n^UNKNOWN^\n正常效果關鍵字"), ["正常效果關鍵字"])
        self.assertEqual(importer._keywords("抽取1\n50%\n#unknown#\n<unknown>", min_length=2), ["抽取1"])


class ServiceTests(unittest.TestCase):
    def test_validates_before_network(self):
        for code in ["", "角色：" + SAMPLE["code"], "https://example.com", "v6l8" + "a" * 4093]:
            with self.subTest(code=code[:20]), patch.object(importer.requests, "Session") as session:
                with self.assertRaises(importer.DeckImportError):
                    importer.decode_share_code(code)
                session.assert_not_called()

    def test_flight_response_and_request_contract(self):
        text = '0:{"a":"$@1"}\n1:' + json.dumps({"ok": True, "preset": PRESET})
        with patch.object(importer.requests, "Session") as factory:
            session = factory.return_value.__enter__.return_value
            session.post.return_value = response(text)
            result = importer.decode_share_code(SAMPLE["code"])
            self.assertEqual(result, PRESET)
            kwargs = session.post.call_args.kwargs
            self.assertEqual(json.loads(kwargs["data"]), [SAMPLE["code"]])
            self.assertEqual(session.post.call_args.args[0], importer.BUILDER_URL)
            self.assertTrue(kwargs["stream"])

    def test_unknown_card_and_network_failure(self):
        with patch.object(importer.requests, "Session") as factory:
            session = factory.return_value.__enter__.return_value
            session.post.return_value = response('1:{"ok":false,"error":"unknownCard"}')
            with self.assertRaisesRegex(importer.DeckImportError, "unknownCard"):
                importer.decode_share_code(SAMPLE["code"])
            session.post.side_effect = importer.requests.Timeout()
            with self.assertRaisesRegex(importer.DeckImportError, "网络"):
                importer.decode_share_code(SAMPLE["code"])

    def test_action_discovery_and_outdated_action_retry(self):
        action = "a" * 40
        script = f'(0,D.createServerReference)("{action}",D.callServer,void 0,D.findSourceMapURL,"decodeGamePresetAction")'
        session = Mock()
        session.get.side_effect = [response('<script src="/_next/static/chunks/deck.js"></script>'), response(script)]
        self.assertEqual(importer._discover_action(session), action)
        with patch.object(importer.requests, "Session") as factory, patch.object(importer, "_discover_action", return_value=action), patch.object(importer, "_DECODE_ACTION", "b" * 40):
            session = factory.return_value.__enter__.return_value
            session.post.side_effect = [response("old", 404), response('1:{"ok":true,"preset":' + json.dumps(PRESET) + '}')]
            self.assertEqual(importer.decode_share_code(SAMPLE["code"]), PRESET)
            self.assertEqual(session.post.call_args.kwargs["headers"]["Next-Action"], action)

    def test_bad_service_response(self):
        for text in ["<html>error</html>", '1:{"ok":"true"}', '1:E{"message":"failed"}']:
            with self.assertRaises(importer.DeckImportError):
                importer.parse_action_response(text)


class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original = [{"name": "原来的卡牌", "effects": ["原效果"], "divine_text": [], "reject_divine": True}]
        self.task = SimpleNamespace(config={"预设卡组": copy.deepcopy(self.original), "游戏语言": "繁体中文"})

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertTrue(predicate())

    def test_import_button_replaces_editor_only_and_cancel_preserves_config(self):
        editor = ui.PresetDeckDialog(self.task)
        self.assertIn("从卡组码导入", [b.text() for b in editor.findChildren(QPushButton)])
        converted = importer.convert_preset(PRESET, "繁体中文")
        with patch.object(ui, "DeckCodeImportDialog") as dialog_type, patch.object(ui.QMessageBox, "information"):
            dialog_type.return_value.exec.return_value = QDialog.Accepted
            dialog_type.return_value.result_data = converted
            editor._import_code()
            self.assertEqual(editor.table.rowCount(), 8)
            self.assertEqual(editor.records, converted[0])
            self.assertEqual(dialog_type.call_args.args[0], "繁体中文")
            self.assertEqual(self.task.config["预设卡组"], self.original)
        editor.reject()
        self.assertEqual(self.task.config["预设卡组"], self.original)

    def test_cancelled_import_does_not_replace_editor(self):
        editor = ui.PresetDeckDialog(self.task)
        with patch.object(ui, "DeckCodeImportDialog") as dialog_type:
            dialog_type.return_value.exec.return_value = QDialog.Rejected
            editor._import_code()
        self.assertEqual(editor.records, self.original)
        editor.close()

    def test_saving_editor_commits_replacement(self):
        records = importer.convert_preset(PRESET)[0]
        with patch.object(ui, "PresetDeckDialog") as dialog_type:
            dialog_type.return_value.exec.return_value = QDialog.Accepted
            dialog_type.return_value.records = records
            ui.open_preset_deck_editor(self.task)
        self.assertEqual(self.task.config["预设卡组"], records)

    def test_async_success_and_failure(self):
        for fail in [False, True]:
            dialog = ui.DeckCodeImportDialog("繁体中文")
            dialog.code_edit.setPlainText(SAMPLE["code"])
            error = importer.DeckImportError("unsupported") if fail else None
            with patch.object(ui, "decode_share_code", return_value=PRESET, side_effect=error):
                dialog._start_import()
                if fail:
                    self.wait_for(lambda: dialog.status_label.text() == "unsupported")
                    self.assertIsNone(dialog.result_data)
                    self.assertTrue(dialog.import_button.isEnabled())
                else:
                    self.wait_for(lambda: dialog.result() == QDialog.Accepted)
                    self.assertEqual(len(dialog.result_data[0]), 8)
                self.wait_for(lambda: not ui._IMPORT_WORKERS)
            dialog.close()

    def test_cancellation_discards_late_network_result(self):
        entered, release = threading.Event(), threading.Event()
        def decode(code):
            entered.set()
            release.wait(3)
            return PRESET
        dialog = ui.DeckCodeImportDialog("简体中文")
        dialog.code_edit.setPlainText(SAMPLE["code"])
        with patch.object(ui, "decode_share_code", side_effect=decode):
            dialog._start_import()
            self.assertTrue(entered.wait(1))
            dialog.reject()
            release.set()
            self.wait_for(lambda: not ui._IMPORT_WORKERS)
        self.assertEqual(dialog.result(), QDialog.Rejected)
        self.assertIsNone(dialog.result_data)


if __name__ == "__main__":
    unittest.main()
