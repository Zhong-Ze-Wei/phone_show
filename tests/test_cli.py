import json
from unittest.mock import Mock

import pytest

from phone_assistant import cli


@pytest.mark.parametrize("options,force,resume", [([], True, False), (["--resume"], False, True), (["--force"], True, False), (["--latest"], True, False)])
def test_sync_refreshes_by_default_and_resume_is_explicit(monkeypatch, options, force, resume):
    run = Mock(return_value={"status": "complete"})
    monkeypatch.setattr("phone_assistant.pipeline.run_sync", run)
    monkeypatch.setattr(cli, "Storage", Mock())
    monkeypatch.setattr("sys.argv", ["phone-assistant", "sync", *options])
    cli.main()
    assert run.call_args.kwargs["force"] is force
    assert run.call_args.kwargs["resume"] is resume
    assert run.call_args.kwargs["latest_only"] is ("--latest" in options)


def test_partial_sync_returns_detectable_exit_code_for_automation(monkeypatch, capsys):
    monkeypatch.setattr("phone_assistant.pipeline.run_sync", lambda **kwargs: {"status": "partial", "completed": 3, "failed": 1})
    monkeypatch.setattr(cli, "Storage", Mock())
    monkeypatch.setattr("sys.argv", ["phone-assistant", "sync"])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 2
    assert '"completed": 3' in capsys.readouterr().out


def test_recommend_accepts_empty_budget_and_defaults_to_unrestricted_storage(monkeypatch, capsys):
    storage = Mock()
    storage.list_phones.return_value = []
    monkeypatch.setattr(cli, "Storage", lambda: storage)
    monkeypatch.setattr("sys.argv", ["phone-assistant", "recommend"])
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["preferences"]["budget_max"] is None
    assert result["preferences"]["min_storage"] == 0
    assert "ranking_policy" not in result
    assert result["preferences"]["sort"] == "newest"


def test_recommend_uses_explicit_browsing_sort_and_used_mode(monkeypatch, capsys):
    storage = Mock()
    storage.list_phones.return_value = []
    run = Mock(return_value={"phones": [], "discovery": {"phones": []}, "catalogue": {"phones": []}})
    monkeypatch.setattr(cli, "Storage", lambda: storage)
    monkeypatch.setattr(cli, "recommend", run)
    monkeypatch.setattr("sys.argv", ["phone-assistant", "recommend", "--budget", "5000", "--purchase-mode", "used"])
    cli.main()
    preferences = run.call_args.args[1]
    assert preferences.budget_max == 5000
    assert preferences.sort == "newest"
    assert preferences.purchase_mode == "used"
    assert preferences.include_history is False


def test_cli_phone_search_keeps_the_complete_catalogue_without_ten_or_sixty_limit(monkeypatch, capsys):
    storage = Mock()
    storage.list_phones.return_value = [{"id": str(index), "name": f"iPhone Example {index}", "brand": "苹果",
        "family_key": str(index), "price": None, "origin": "legacy", "availability": "historical"} for index in range(65)]
    monkeypatch.setattr(cli, "Storage", lambda: storage)
    monkeypatch.setattr("sys.argv", ["phone-assistant", "recommend", "--query", "iPhone"])
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["phones"] == []
    assert result["catalogue"]["total"] == result["catalogue"]["returned"] == len(result["catalogue"]["phones"]) == 65
    assert all("history" in record["catalogue_codes"] for record in result["catalogue"]["phones"])


@pytest.mark.parametrize("options", [
    ["--budget", "nan"], ["--budget", "inf"], ["--budget", "0"],
    ["--budget", "4000", "--min-budget", "nan"],
    ["--budget", "4000", "--storage", "inf"],
    ["--budget", "4000", "--storage", "-1"],
])
def test_invalid_numeric_preferences_cannot_bypass_budget(monkeypatch, options):
    run = Mock()
    monkeypatch.setattr(cli, "Storage", Mock())
    monkeypatch.setattr(cli, "recommend", run)
    monkeypatch.setattr("sys.argv", ["phone-assistant", "recommend", *options])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 1
    run.assert_not_called()
