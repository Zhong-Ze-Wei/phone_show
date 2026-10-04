from unittest.mock import Mock

from fastapi.testclient import TestClient

from phone_assistant.config import Settings
from phone_assistant.server import create_app


def client_for(phones=None):
    storage = Mock()
    storage.list_phones.return_value = phones or []
    storage.summary.return_value = {"records": len(phones or [])}
    storage.get_phone.side_effect = lambda id: next((phone for phone in (phones or []) if phone["id"] == id), None)
    return TestClient(create_app(storage=storage, settings=Settings("private-test-secret")))


def test_metadata_never_returns_api_key():
    response = client_for().get("/api/meta")
    assert response.status_code == 200
    assert response.json()["api_configured"] is True
    assert "private-test-secret" not in response.text


def test_reversed_budget_rejected_before_recommendation():
    response = client_for().post("/api/recommend", json={"budget_min": 5000, "budget_max": 3000})
    assert response.status_code == 422


def test_unknown_priority_rejected():
    assert client_for().post("/api/recommend", json={"budget_max": 3000, "priorities": ["imaginary-benchmark"]}).status_code == 422


def test_unknown_phone_returns_404():
    assert client_for().get("/api/phones/missing").status_code == 404


def test_explain_rejects_missing_candidate_without_api_call():
    assert client_for().post("/api/explain", json={"ids": ["missing"], "preferences": {"budget_max": 3000}}).status_code == 404


def test_filter_preserves_unknowns_and_budget_boundary():
    from datetime import datetime, timezone

    phones = [{"id": "test", "name": "测试型号", "brand": "测试", "price": 3000, "storage_gb": 256, "origin": "zol", "availability": "listed", "fetched_at": datetime.now(timezone.utc).isoformat()}]
    response = client_for(phones).post("/api/recommend", json={"budget_max": 3000})
    assert response.status_code == 200
    record = response.json()["phones"][0]
    assert record["price"] == 3000
    assert record["metrics"]["camera"] is None
    assert "待补充" in " ".join(record["tradeoffs"])


def test_partial_coverage_without_request_errors_is_not_announced_as_complete(monkeypatch):
    from phone_assistant.server import SyncJob

    monkeypatch.setattr("phone_assistant.pipeline.run_sync", lambda **kwargs: {"status": "partial", "errors": [], "list_count_mismatch": True})
    job = SyncJob(Mock())
    job.run()
    assert job.snapshot()["stage"] == "部分完成"
    assert "覆盖仍有缺口" in job.snapshot()["message"]


def test_comparison_recalculates_same_preferences_and_marks_out_of_budget():
    from datetime import datetime, timezone

    phones = [{"id": "a", "name": "手机A", "price": 3999, "ram_gb": 12, "storage_gb": 512,
        "battery_mah": 7000, "charging_w": 100, "origin": "zol", "availability": "listed",
        "fetched_at": datetime.now(timezone.utc).isoformat()}]
    client = client_for(phones)
    result = client.post("/api/compare", json={"ids": ["a"], "preferences": {"budget_max": 3000, "priorities": ["battery"]}})
    assert result.status_code == 200
    phone = result.json()["phones"][0]
    assert phone["metrics"]["battery"] is not None
    assert phone["budget_warning"] == "超出当前预算范围"
    assert phone["price"] == 3999


def test_sort_is_explicit_and_validated():
    assert client_for().post("/api/recommend", json={"budget_max": 3000}).json()["preferences"]["sort"] == "recommended"
    assert client_for().post("/api/recommend", json={"budget_max": 3000, "sort": "recommended"}).status_code == 200
    assert client_for().post("/api/recommend", json={"budget_max": 3000, "sort": "newest"}).json()["preferences"]["sort"] == "newest"
    assert client_for().post("/api/recommend", json={"budget_max": 3000, "sort": "imaginary"}).status_code == 422


def test_purchase_mode_is_validated_and_does_not_enable_history():
    result = client_for().post("/api/recommend", json={"budget_max": 3000, "purchase_mode": "used"})
    assert result.status_code == 200
    payload = result.json()
    assert payload["preferences"]["purchase_mode"] == "used"
    assert payload["preferences"]["include_history"] is False
    assert payload["ranking_policy"]["weights"]["recency"] == 0
    assert client_for().post("/api/recommend", json={"budget_max": 3000, "purchase_mode": "refurbished"}).status_code == 422


def test_compare_and_recommend_share_explainable_ranking():
    from datetime import datetime, timezone

    phones = [{"id": "a", "name": "手机A", "brand": "荣耀", "price": 2500, "storage_gb": 256,
        "battery_mah": 6000, "charging_w": 80, "origin": "zol", "availability": "listed",
        "fetched_at": datetime.now(timezone.utc).isoformat(), "release_date": "2023-01-01"}]
    client = client_for(phones)
    preferences = {"budget_max": 3000, "purchase_mode": "used", "priorities": ["battery"]}
    recommended = client.post("/api/recommend", json=preferences).json()["phones"][0]
    compared = client.post("/api/compare", json={"ids": ["a"], "preferences": preferences}).json()["phones"][0]
    for field in ("score", "recommendation_score", "ranking_breakdown", "ranking_reasons"):
        assert recommended[field] == compared[field]


def test_new_source_search_is_not_silently_hidden_by_budget():
    from datetime import datetime, timezone
    phone = {"id": "official:vivo:x500", "name": "vivo X500", "brand": "vivo", "price": None, "storage_gb": None,
        "origin": "official", "availability": "unknown", "fetched_at": datetime.now(timezone.utc).isoformat(), "new_from_source": True}
    result = client_for([phone]).post("/api/recommend", json={"budget_max": 3000, "query": "X500"}).json()
    assert result["total"] == 0
    assert result["discovery"]["phones"][0]["name"] == "vivo X500"
    assert "不能确认是否在预算内" in " ".join(result["discovery"]["phones"][0]["discovery_reasons"])


def test_recommend_accepts_missing_budget_without_assuming_4000():
    client = client_for()
    response = client.post("/api/recommend", json={})
    assert response.status_code == 200
    assert response.json()["preferences"]["budget_max"] is None
    assert response.json()["preferences"]["min_storage"] == 0
    assert response.json()["ranking_policy"]["weights"] == {"usage": 0.85, "value": 0.0, "recency": 0.1, "brand": 0.05}


def test_compare_and_explain_accept_omitted_preferences_without_hidden_budget(monkeypatch):
    from phone_assistant import server

    explain = Mock(return_value={"content": "用途匹配说明", "sources": []})
    monkeypatch.setattr(server, "explain", explain)
    client = client_for([{"id": "a", "name": "选中的手机", "price": 9999}])
    for path in ("/api/compare", "/api/explain"):
        omitted = client.post(path, json={"ids": ["a"]})
        no_budget = client.post(path, json={"ids": ["a"], "preferences": {"budget_max": None}})
        assert omitted.status_code == no_budget.status_code == 200
        if path == "/api/compare":
            assert omitted.json()["phones"][0]["budget_warning"] is None
            assert no_budget.json()["phones"][0]["budget_warning"] is None
    assert explain.call_args.args[1].budget_max is None


def test_all_selection_endpoints_accept_more_than_three_and_preserve_all_ids(monkeypatch):
    from phone_assistant import server

    phones = [{"id": str(index), "name": f"手机{index}", "price": 3000 + index} for index in range(7)]
    explain = Mock(return_value={"content": "比较七款", "sources": []})
    monkeypatch.setattr(server, "explain", explain)
    client = client_for(phones)
    ids = [phone["id"] for phone in phones]
    compared = client.post("/api/compare", json={"ids": ids})
    assert compared.status_code == 200
    assert [record["id"] for record in compared.json()["phones"]] == ids
    assert all(record["budget_warning"] is None for record in compared.json()["phones"])
    assert client.post("/api/explain", json={"ids": ids}).status_code == 200
    assert [record["id"] for record in explain.call_args.args[0]] == ids


def test_phone_search_catalogue_includes_unpriced_official_and_historical_records_without_new_gate():
    from datetime import datetime, timezone

    rows = [{"id": "17", "name": "iPhone 17", "brand": "苹果", "family_key": "17", "price": None,
        "storage_gb": None, "origin": "official", "availability": "unknown", "os_family": "iOS",
        "fetched_at": datetime.now(timezone.utc).isoformat(), "source_url": "https://www.apple.com.cn/iphone-17/"},
        {"id": "16", "name": "iPhone 16(128GB)", "brand": "苹果", "family_key": "16", "price": 5999,
        "storage_gb": 128, "origin": "legacy", "availability": "historical", "os_family": "iOS", "fetched_at": None}]
    response = client_for(rows).post("/api/recommend", json={"query": "iPhone", "budget_max": None})
    assert response.status_code == 200
    result = response.json()
    assert result["phones"] == result["discovery"]["phones"] == []
    assert result["catalogue"]["total"] == result["catalogue"]["returned"] == 2
    records = {record["id"]: record for record in result["catalogue"]["phones"]}
    assert records["17"]["catalogue_codes"] == ["availability_unknown", "unknown_price"]
    assert records["16"]["catalogue_codes"] == ["history", "stale_price"]
    assert all(record["recommendation_eligible"] is False for record in records.values())


def test_explicit_zero_or_nonfinite_budget_is_invalid_in_every_filter_endpoint():
    client = client_for()
    for path, base in (("/api/recommend", {}), ("/api/compare", {"ids": ["a"]}),
            ("/api/explain", {"ids": ["a"]}), ("/api/chat", {"message": "你好"})):
        for value in (0, -1):
            payload = {**base, "budget_max": value} if path == "/api/recommend" else {**base, "preferences": {"budget_max": value}}
            assert client.post(path, json=payload).status_code == 422
    for value in ("NaN", "Infinity"):
        response = client.post("/api/recommend", content='{"budget_max":' + value + '}', headers={"Content-Type": "application/json"})
        assert response.status_code == 422
