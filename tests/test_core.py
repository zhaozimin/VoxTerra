#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[INPUT]: 标准库 unittest/mock/zipfile；被测纯逻辑模块 voicelog/{model_fetch,update_check,i18n}
[OUTPUT]: 可执行测试套件——`python -m unittest tests.test_core`（或 `python tests/test_core.py`）
[POS]: voicelog 的「行为锚点」。把不依赖音频/UI 的核心逻辑钉死，改代码先跑这里、绿了再打包，
       终结「每改一处就重打包验证」的浪费。AppKit 相关用例在非 macOS 自动跳过。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
import io
import sys
import zipfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 只测纯逻辑模块——它们仅依赖标准库，import 无重副作用(不碰 mlx/sounddevice/pyobjc)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voicelog"))
import model_fetch          # noqa: E402
import update_check         # noqa: E402
import auto_update          # noqa: E402
import i18n                 # noqa: E402


# ============================================================================
#  更新提示：版本号解析与比较(纯函数)
# ============================================================================
class TestVersionCompare(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(update_check.parse_version("v0.9.3"), (0, 9, 3))
        self.assertEqual(update_check.parse_version("0.9.3-win-beta"), (0, 9, 3))
        self.assertEqual(update_check.parse_version(""), (0,))

    def test_is_newer(self):
        self.assertTrue(update_check.is_newer("0.9.4", "0.9.3"))
        self.assertTrue(update_check.is_newer("0.10.0", "0.9.9"))    # 10 > 9,非字典序
        self.assertTrue(update_check.is_newer("1.0", "0.9.3"))       # 补零比较
        self.assertFalse(update_check.is_newer("0.9.3", "0.9.3"))    # 相等不提示
        self.assertFalse(update_check.is_newer("0.9.2", "0.9.3"))    # 旧不提示
        self.assertFalse(update_check.is_newer("0.9.3-x", "0.9.3"))  # 后缀不影响数字相等


# ============================================================================
#  模型四态状态机(纯函数,mac/win 共用的单一真相源)
# ============================================================================
class TestModelStatusKey(unittest.TestCase):
    def test_states(self):
        k = model_fetch.model_status_key
        self.assertEqual(k(True, False, True), "model_dling")    # 下载中优先
        self.assertEqual(k(True, True, True), "model_dling")
        self.assertEqual(k(False, True, True), "model_check")    # 已就绪
        self.assertEqual(k(False, True, False), "model_check")
        self.assertEqual(k(False, False, True), "model_get")     # 托管缺失→可下载
        self.assertEqual(k(False, False, False), "model_missing")  # 直连缺失→配置错


# ============================================================================
#  model_ready：体积门槛(挡零字节/截断残留冒充就绪)
# ============================================================================
class TestModelReady(unittest.TestCase):
    def test_size_threshold(self):
        d = Path(tempfile.mkdtemp())
        self.assertFalse(model_fetch.model_ready(d))               # 空目录
        (d / "weights.npz").write_bytes(b"0" * 100)
        self.assertFalse(model_fetch.model_ready(d))               # 100B 残留
        (d / "weights.npz").write_bytes(b"0" * (2 << 20))
        self.assertTrue(model_fetch.model_ready(d))                # 2MB 足量

    def test_model_bin(self):
        d = Path(tempfile.mkdtemp())
        (d / "model.bin").write_bytes(b"0" * (2 << 20))
        self.assertTrue(model_fetch.model_ready(d))

    def test_nonexistent(self):
        self.assertFalse(model_fetch.model_ready("/no/such/dir/xyz"))


# ============================================================================
#  download_model：完整性校验(截断即失败) + 正常 zip 解压就绪
# ============================================================================
class _FakeResp:
    """伪 HTTP 响应：支持 with 上下文 + headers.get + read(n)，喂给 download_model。"""
    def __init__(self, data: bytes, content_length):
        self._buf = io.BytesIO(data)
        self.headers = {"Content-Length": str(content_length)} if content_length is not None else {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self._buf.read(n)


def _zip_with_model() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("whisper-mlx-turbo/weights.safetensors", b"0" * (2 << 20))
        z.writestr("whisper-mlx-turbo/config.json", b"{}")
    return buf.getvalue()


class TestDownloadModel(unittest.TestCase):
    def test_truncated_returns_false(self):
        # Content-Length 说 100，实际只给 50 → 字节对不上 → False(不拿截断 zip 解压)
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(b"x" * 50, 100)):
            dest = Path(tempfile.mkdtemp()) / "m"
            self.assertFalse(model_fetch.download_model("http://x/z.zip", dest))

    def test_complete_zip_returns_true(self):
        data = _zip_with_model()
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(data, len(data))):
            dest = Path(tempfile.mkdtemp()) / "whisper-mlx-turbo"
            self.assertTrue(model_fetch.download_model("http://x/z.zip", dest))
            self.assertTrue(model_fetch.model_ready(dest))         # 解压后确实就绪

    def test_no_content_length_ok(self):
        # 无 Content-Length(total=0)时跳过字节校验,不应误判失败
        data = _zip_with_model()
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(data, None)):
            dest = Path(tempfile.mkdtemp()) / "whisper-mlx-turbo"
            self.assertTrue(model_fetch.download_model("http://x/z.zip", dest))


# ============================================================================
#  自动更新：下载地址拼装 / .app 根推断(纯函数) + 校验闸负向用例
# ============================================================================
class TestAutoUpdate(unittest.TestCase):
    def test_asset_url_mac(self):
        u = auto_update.asset_url("0.9.4", "mac")
        self.assertEqual(u, "https://github.com/zhaozimin/Recorder/releases/download/v0.9.4/VoiceLog-0.9.4.dmg")
        self.assertEqual(auto_update.asset_url("v0.9.4", "mac"), u)   # 容忍 v 前缀

    def test_asset_url_win(self):
        self.assertEqual(
            auto_update.asset_url("0.9.4", "win"),
            "https://github.com/zhaozimin/Recorder/releases/download/v0.9.4-win-beta/VoiceLog-0.9.4-Setup.exe")

    def test_app_bundle_root(self):
        self.assertEqual(
            auto_update.app_bundle_root("/Applications/言壤.app/Contents/MacOS/VoiceLog"),
            "/Applications/言壤.app")
        self.assertIsNone(auto_update.app_bundle_root("/Users/x/voicelog/voicelog_menubar.py"))

    @unittest.skipUnless(sys.platform == "darwin", "codesign 仅 macOS")
    def test_verify_rejects_non_app(self):
        # 校验闸对不存在/非签名路径必须判否(防把垃圾当更新覆盖上去)
        self.assertFalse(auto_update.verify_macos_app("/tmp/no_such_voicelog.app"))
        d = tempfile.mkdtemp()
        self.assertFalse(auto_update.verify_macos_app(d))


# ============================================================================
#  i18n：三语键齐全(无漏翻) + 关键文案
# ============================================================================
class TestI18nParity(unittest.TestCase):
    def test_keys_match_across_langs(self):
        base = set(i18n.STRINGS["zh"])
        for lang, d in i18n.STRINGS.items():
            ks = set(d)
            self.assertEqual(ks, base,
                             f"{lang} 键不一致：缺={base - ks}，多={ks - base}")

    def test_app_name(self):
        i18n.set_language("zh"); self.assertEqual(i18n.t("app_name"), "言壤")
        i18n.set_language("en"); self.assertEqual(i18n.t("app_name"), "VoiceLog")

    def test_new_keys_present(self):
        for k in ("model_check", "model_get", "model_dling", "model_missing",
                  "model_missing_t", "model_missing_b", "cur_version",
                  "upd_checking", "upd_latest", "upd_avail", "upd_downloading",
                  "upd_confirm_t", "upd_confirm_b", "upd_ok", "upd_cancel",
                  "upd_dl_fail", "upd_fail_t", "upd_dev"):
            self.assertIn(k, i18n.STRINGS["zh"])

    def test_format_placeholders(self):
        i18n.set_language("zh")
        self.assertIn("42", i18n.t("model_dling", p=42))
        s = i18n.t("upd_avail", app="言壤", v="0.9.4")
        self.assertIn("0.9.4", s)
        self.assertIn("言壤", s)
        self.assertIn("v0.9.3", i18n.t("cur_version", app="言壤", v="0.9.3"))


# ============================================================================
#  关键词窗口 Cmd+V 粘贴(macOS + pyobjc 才跑,否则跳过)
# ============================================================================
@unittest.skipUnless(sys.platform == "darwin", "AppKit 仅 macOS")
class TestPasteKeyWindow(unittest.TestCase):
    def test_cmd_v_pastes(self):
        try:
            from AppKit import (NSApplication, NSPasteboard, NSPasteboardTypeString, NSEvent,
                                NSEventTypeKeyDown, NSEventModifierFlagCommand)
            import replace_ui
        except Exception as e:
            self.skipTest(f"pyobjc 不可用: {e}")
        NSApplication.sharedApplication()
        pb = NSPasteboard.generalPasteboard(); pb.clearContents()
        pb.setString_forType_("PASTE_OK", NSPasteboardTypeString)
        w = replace_ui.ReplaceWindow("orig\n")
        w.win.makeFirstResponder_(w.tv)
        ev = NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
            NSEventTypeKeyDown, (0, 0), NSEventModifierFlagCommand, 0,
            w.win.windowNumber(), None, "v", "v", False, 9)
        self.assertTrue(bool(w.win.performKeyEquivalent_(ev)))
        self.assertIn("PASTE_OK", str(w.tv.string()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
