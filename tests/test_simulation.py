from simulation import build_bridge_mocks, covers_every_bridge_tool

CTX = object()


def test_default_mocks_cover_all_bridge_tools() -> None:
    mocks = build_bridge_mocks()
    assert covers_every_bridge_tool(mocks)


def test_launch_app_default_and_userdata_override() -> None:
    assert build_bridge_mocks()["launch_app"](CTX, "discord") == "Launching discord."
    custom = build_bridge_mocks({"launch_result": "Opening YouTube now."})
    assert custom["launch_app"](CTX, "youtube") == "Opening YouTube now."


def test_notes_flow_keeps_state() -> None:
    mocks = build_bridge_mocks({"notes": ["buy milk"]})
    assert mocks["list_notes"](CTX) == "1. buy milk"
    assert mocks["create_note"](CTX, "pick up dry cleaning") == (
        "Noted: pick up dry cleaning"
    )
    assert mocks["list_notes"](CTX) == "1. buy milk 2. pick up dry cleaning"
    assert mocks["delete_note"](CTX, 1) == "Deleted note 1."
    assert mocks["list_notes"](CTX) == "1. pick up dry cleaning"
    assert mocks["delete_note"](CTX, 99) == "There is no note with id 99."


def test_create_note_rejects_empty_text() -> None:
    assert "note content" in build_bridge_mocks()["create_note"](CTX, "")


def test_system_status_reflects_userdata() -> None:
    status = {
        "cpu_percent": 12.0,
        "memory_used_gb": 4.0,
        "memory_total_gb": 16.0,
        "disk_free_gb": 100.0,
    }
    out = build_bridge_mocks({"status": status})["get_system_status"](CTX)
    assert "CPU usage is 12.0 percent" in out
    assert "4.0 of 16.0 gigabytes" in out
    assert "100.0 gigabytes free" in out


def test_timers_flow_keeps_state() -> None:
    mocks = build_bridge_mocks()
    assert "No timers" in mocks["list_timers"](CTX)
    assert mocks["start_timer"](CTX, "pasta", 8) == (
        "Timer 'pasta' set for 8 minute(s). I will let you know when it finishes."
    )
    assert "pasta" in mocks["list_timers"](CTX)
    assert (
        mocks["start_timer"](CTX, "lazy", -1)
        == "Please provide a positive number of minutes."
    )
    assert mocks["cancel_timer"](CTX, 1) == "Cancelled timer 1."
    assert "No timers" in mocks["list_timers"](CTX)
    assert "no running timer" in mocks["cancel_timer"](CTX, 1)


def test_reminders_flow_keeps_state() -> None:
    mocks = build_bridge_mocks()
    assert "no upcoming reminders" in mocks["list_reminders"](CTX)
    assert mocks["schedule_reminder"](CTX, "stretch", "2026-09-15T20:00:00") == (
        "Reminder set for 2026-09-15T20:00:00: stretch."
    )
    assert "20:00" in mocks["list_reminders"](CTX)
    assert mocks["cancel_reminder"](CTX, 1) == "Cancelled reminder 1."
    assert "no reminder" in mocks["cancel_reminder"](CTX, 1)


def test_screenshot_files_and_media() -> None:
    mocks = build_bridge_mocks(
        {
            "file_matches": ["C:/Users/ci/Documents/tax.pdf"],
            "screenshot_path": "C:/shot.png",
        }
    )
    assert "shot.png" in mocks["take_screenshot"](CTX)
    assert "tax.pdf" in mocks["search_files"](CTX, "tax")
    assert mocks["open_file"](CTX, "C:/report.pdf") == "Opened C:/report.pdf."
    assert mocks["media_control"](CTX, "next") == "Media: next."


def test_empty_search_is_friendly() -> None:
    assert "Nothing named" in build_bridge_mocks()["search_files"](CTX, "nothing-here")


def test_timers_and_reminders_seed_from_userdata() -> None:
    mocks = build_bridge_mocks(
        {
            "timers": [{"label": "tea", "minutes": 3}],
            "reminders": [{"label": "call mum", "at": "2026-09-16T09:00:00"}],
        }
    )
    assert "tea" in mocks["list_timers"](CTX)
    assert "call mum" in mocks["list_reminders"](CTX)
    assert mocks["cancel_timer"](CTX, 1) == "Cancelled timer 1."
    assert "no reminder" in mocks["cancel_reminder"](CTX, 2)


def test_seeded_timers_get_ordered_ids() -> None:
    mocks = build_bridge_mocks({"timers": [{"label": "tea", "minutes": 3}]})
    assert mocks["cancel_timer"](CTX, 1) == "Cancelled timer 1."
    assert "no running timer" in mocks["cancel_timer"](CTX, 1)
    assert "No timers" in mocks["list_timers"](CTX)
