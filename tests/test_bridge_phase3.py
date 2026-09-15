import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from bridge import files, launcher, media, screenshot


class TestLauncher:
    def test_presets_resolve_known_app(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        spawns: list[list[str]] = []
        monkeypatch.setattr(
            launcher.subprocess,
            "Popen",
            lambda argv, **kw: spawns.append(argv),
        )
        ok, message = launcher.launch_app("notepad", apps_path=tmp_path / "apps.json")
        assert ok
        assert "notepad" in message.lower()
        assert spawns and spawns[0] == ["notepad.exe"]

    def test_unknown_app_returns_friendly_error(self, tmp_path: Path) -> None:
        ok, message = launcher.launch_app(
            "definitely-not-an-app", apps_path=tmp_path / "apps.json"
        )
        assert ok is False
        assert "could not find an app named" in message

    def test_user_config_overrides_preset(self, tmp_path: Path) -> None:
        cfg = tmp_path / "apps.json"
        cfg.write_text(json.dumps({"notepad": ["sonic.exe"]}), encoding="utf-8")
        commands = launcher.apps_commands(apps_path=cfg)
        assert commands["notepad"] == ["sonic.exe"]

    def test_case_insensitive_names(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(launcher.subprocess, "Popen", lambda argv, **kw: None)
        ok, _ = launcher.launch_app("NOTEPAD", apps_path=tmp_path / "apps.json")
        assert ok

    @staticmethod
    def _apps_fixture() -> list[tuple[str, str]]:
        return [
            ("Discord", "com.squirrel.Discord.Discord"),
            ("Steam", "{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}\\Steam\\Steam.exe"),
            ("WhatsApp", "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"),
            ("Spotify", "Spotify.exe"),
        ]

    @staticmethod
    def _reset_apps_cache(monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(launcher, "_apps_cache", None)
        monkeypatch.setattr(launcher, "_apps_cache_at", 0.0)

    def test_start_apps_backend_launches_any_installed_app(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._reset_apps_cache(monkeypatch)
        opened: list[str] = []
        monkeypatch.setattr(
            launcher, "_start_apps_list", lambda force=False: self._apps_fixture()
        )
        monkeypatch.setattr(launcher, "_find_start_menu_shortcuts", lambda name: None)
        monkeypatch.setattr(launcher.os, "startfile", lambda p: opened.append(p))
        ok, message = launcher.launch_app("discord", apps_path=tmp_path / "apps.json")
        assert ok
        assert opened and opened[0].startswith("shell:AppsFolder\\")
        assert "com.squirrel.Discord.Discord" in opened[0]
        assert message.lower().startswith("launching discord")

    def test_start_menu_shortcut_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._reset_apps_cache(monkeypatch)
        opened: list[str] = []
        lnk = tmp_path / "VLC Media Player.lnk"
        monkeypatch.setattr(
            launcher, "_start_apps_list", lambda force=False: self._apps_fixture()
        )
        monkeypatch.setattr(launcher, "_find_start_menu_shortcuts", lambda name: lnk)
        monkeypatch.setattr(launcher.os, "startfile", lambda p: opened.append(p))
        ok, message = launcher.launch_app("vlc", apps_path=tmp_path / "apps.json")
        assert ok
        assert opened and opened[0] == lnk
        assert "vlc" in message.lower()

    def test_fuzzy_name_match_is_case_insensitive(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._reset_apps_cache(monkeypatch)
        opened: list[str] = []
        monkeypatch.setattr(
            launcher, "_start_apps_list", lambda force=False: self._apps_fixture()
        )
        monkeypatch.setattr(launcher, "_find_start_menu_shortcuts", lambda name: None)
        monkeypatch.setattr(launcher.os, "startfile", lambda p: opened.append(p))
        ok, _ = launcher.launch_app("WHATSA", apps_path=tmp_path / "apps.json")
        assert ok
        assert "WhatsAppDesktop" in opened[0]

    def test_unknown_app_still_friendly(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._reset_apps_cache(monkeypatch)
        monkeypatch.setattr(
            launcher, "_start_apps_list", lambda force=False: self._apps_fixture()
        )
        monkeypatch.setattr(launcher, "_find_start_menu_shortcuts", lambda name: None)
        ok, message = launcher.launch_app(
            "some-unknown-program", apps_path=tmp_path / "apps.json"
        )
        assert ok is False
        assert "could not find" in message.lower()

    def test_start_apps_list_fetched_once_per_window(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._reset_apps_cache(monkeypatch)
        runs: list[int] = []

        def fake_ps(_script: str) -> str:
            runs.append(1)
            return (
                "Discord\tcom.squirrel.Discord.Discord\n"
                "Steam\t{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}\\Steam\\Steam.exe\n"
            )

        monkeypatch.setattr(launcher, "_run_powershell", fake_ps)
        monkeypatch.setattr(launcher, "_find_start_menu_shortcuts", lambda name: None)
        monkeypatch.setattr(launcher.os, "startfile", lambda p: None)
        launcher.launch_app("discord", apps_path=tmp_path / "apps.json")
        launcher.launch_app("steam", apps_path=tmp_path / "apps.json")
        assert len(runs) == 1

    def test_prewarm_builds_both_caches(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._reset_apps_cache(monkeypatch)
        monkeypatch.setattr(launcher, "_shortcuts_index", None)
        monkeypatch.setattr(launcher, "_shortcuts_index_at", 0.0)
        monkeypatch.setattr(
            launcher,
            "_run_powershell",
            lambda _script: "Discord\tcom.squirrel.Discord.Discord\n",
        )
        menu = tmp_path / "menu"
        menu.mkdir()
        (menu / "Discord.lnk").write_text("x", encoding="utf-8")
        monkeypatch.setattr(launcher, "_START_MENU_DIRS", (menu,))
        monkeypatch.setattr(launcher.os, "startfile", lambda p: None)

        launcher.prewarm_app_list()

        assert launcher._apps_cache == [("Discord", "com.squirrel.Discord.Discord")]
        assert launcher._shortcuts_index == [menu / "Discord.lnk"]
        ok, message = launcher.launch_app("discord", apps_path=tmp_path / "apps.json")
        assert ok and "Discord" in message

    def test_open_file_refuses_outside_home(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A path outside the user's profile (e.g. %SystemRoot%) must be refused.
        opened: list[str] = []
        monkeypatch.setattr(launcher.os, "startfile", lambda p: opened.append(repr(p)))
        target = Path(os.environ["SYSTEMROOT"])
        assert target.exists()
        ok, message = launcher.open_file(str(target))
        assert ok is False
        assert "outside your user profile" in message
        assert opened == []

    def test_open_file_missing_path(self, tmp_path: Path) -> None:
        ok, message = launcher.open_file(str(tmp_path / "nope.txt"))
        assert ok is False
        assert "could not find" in message

    def test_open_file_within_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        opened: list[str] = []
        monkeypatch.setattr(launcher.os, "startfile", lambda p: opened.append(repr(p)))
        ok, message = launcher.open_file(str(Path.home()))
        assert ok
        assert "Opened" in message
        assert opened


class TestFiles:
    def test_finds_matching_filenames(self, tmp_path: Path) -> None:
        (tmp_path / "report-final.pdf").write_text("", encoding="utf-8")
        (tmp_path / "todo.txt").write_text("", encoding="utf-8")
        sub = tmp_path / "docs"
        sub.mkdir()
        (sub / "report-draft.pdf").write_text("", encoding="utf-8")

        results = files.search_files("report", root=str(tmp_path))
        assert len(results) == 2
        names = {Path(r).name for r in results}
        assert names == {"report-final.pdf", "report-draft.pdf"}

    def test_matches_directories(self, tmp_path: Path) -> None:
        (tmp_path / "photos").mkdir()
        results = files.search_files("photo", root=str(tmp_path))
        assert any(Path(r).name == "photos" for r in results)

    def test_skips_noise_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "report-secret.pdf").write_text(
            "", encoding="utf-8"
        )
        (tmp_path / "report-public.pdf").write_text("", encoding="utf-8")
        results = files.search_files("report", root=str(tmp_path))
        assert all("node_modules" not in r for r in results)
        assert len(results) == 1

    def test_empty_query_returns_nothing(self, tmp_path: Path) -> None:
        assert files.search_files("", root=str(tmp_path)) == []

    def test_zero_time_budget_returns_immediately(self, tmp_path: Path) -> None:
        (tmp_path / "quarterly-report.pdf").write_text("", encoding="utf-8")
        results = files.search_files("report", root=str(tmp_path), time_budget=0.0)
        assert isinstance(results, list)

    def test_missing_root_returns_nothing(self, tmp_path: Path) -> None:
        assert files.search_files("x", root=str(tmp_path / "absent")) == []


class TestMedia:
    def test_known_actions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pressed: list[int] = []
        monkeypatch.setattr(media, "_send_key", lambda code: pressed.append(code))
        for action in (
            "play_pause",
            "next",
            "previous",
            "volume_up",
            "volume_down",
            "mute",
        ):
            ok, _ = media.media_control(action)
            assert ok is True
        assert len(pressed) == 6

    def test_unknown_action(self) -> None:
        ok, message = media.media_control("shuffle")
        assert ok is False
        assert "not a media action" in message


class TestScreenshot:
    def test_screenshot_creates_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        class FakeDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 9, 14, 12, 30, 0)

        monkeypatch.setattr(screenshot, "datetime", FakeDateTime)
        expected = tmp_path / "screenshot-20260914-123000.png"

        def fake_run(script):
            expected.write_bytes(b"png")

        monkeypatch.setattr(screenshot, "_run_powershell", fake_run)
        ok, path = screenshot.take_screenshot(out_dir=tmp_path)
        assert ok is True
        assert path == str(expected)
        assert expected.exists()

    def test_screenshot_failure_reported(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def raise_oserror(script):
            raise OSError("boom")

        monkeypatch.setattr(screenshot, "_run_powershell", raise_oserror)
        ok, message = screenshot.take_screenshot(out_dir=tmp_path)
        assert ok is False
        assert "boom" in message
