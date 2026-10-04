"""公开页布局、失败隔离、断点恢复与同步互斥；测试不联网。"""

import hashlib
import json
import sqlite3

import httpx
import pytest
from filelock import FileLock

from phone_assistant import crawler, pipeline
from phone_assistant.crawler import (
    BASE_URL, LIST_URL, PageValidationError, parse_listing, parse_parameters,
    parse_product, parse_series, parse_series_parameters, parse_discovery, parse_brand_directory,
)


def page(body, title="手机报价-ZOL中关村在线"):
    return f"<html><head><title>{title}</title></head><body>{body}<!--{'navigation ' * 50}--></body></html>"


def listed(identifier="100", *, grid=False, price="￥4399"):
    body = (
        f'<h3><a href="/cell_phone/index{identifier}.shtml">小米测试手机(12GB/256GB)'
        '<span> 广告宣传</span></a></h3>'
        f'<a href="/100/{identifier}/param.shtml">更多参数</a>'
        '<span class="price price-normal">' + price + '</span>'
        '<img .src="https://example.test/phone.jpg">'
    )
    if grid:
        return f'<ul class="pic-mode-box"><li data-follow-id="p{identifier}">{body}</li></ul>'
    return f'<div class="list-item clearfix" data-follow-id="p{identifier}">{body}</div>'


def parameters(identifier="100"):
    rows = "".join(
        f'<tr><th>{key}</th><td>{value}<em class="edit-param">纠错</em></td></tr>'
        for key, value in {
            "CPU型号": "骁龙8 Elite", "电池容量": "6000mAh", "有线充电": "90W",
            "运行内存": "12GB", "机身内存": "256GB", "电商报价": "￥4599",
        }.items()
    )
    return page(
        '<div class="breadcrumb"><a href="/cell_phone_index/subcate57_80_list_1.html">小米手机</a></div>'
        f'<h3 class="goods-card__title"><a href="/cell_phone/index{identifier}.shtml">小米测试手机</a></h3>'
        f'<div class="detailed-parameters"><table>{rows}</table></div>'
    )


@pytest.mark.parametrize("grid", [False, True])
def test_parse_both_list_layouts_without_promotional_name(grid):
    parsed = parse_listing(page(listed(grid=grid) + '<div class="total">共 1 款</div>'))
    assert parsed.total == 1
    assert parsed.phones[0]["id"] == "100"
    assert parsed.phones[0]["name"] == "小米测试手机(12GB/256GB)"
    assert parsed.phones[0]["price"] == "￥4399"
    assert parsed.phones[0]["image_url"] == "https://example.test/phone.jpg"
    assert parsed.layout == ("grid" if grid else "list")


def test_pagination_preserves_real_public_grid_urls():
    second = BASE_URL + "/cell_phone_index/subcate57_0_list_1_0_1_2_0_2.html"
    parsed = parse_listing(page(listed(grid=True) + f'<div class="pagebar"><a href="{second}">2</a></div>'))
    assert second in parsed.page_urls


def test_newest_sort_is_discovered_from_source_link():
    newest = BASE_URL + "/cell_phone_index/subcate57_0_list_1_0_9_2_0_1.html"
    parsed = parse_listing(page(listed(grid=True) + f'<a href="{newest}">时间</a>'))
    assert parsed.sort_urls == [newest]


def test_all_declared_pages_use_the_source_pagination_template():
    second = BASE_URL + "/cell_phone_index/subcate57_0_list_1_0_1_2_0_2.html"
    parsed = parse_listing(page(
        listed(grid=True) + '<span class="small-page-active">1 /13</span>'
        + f'<div class="pagebar"><a href="{second}">2</a></div>'
    ))
    assert BASE_URL + "/cell_phone_index/subcate57_0_list_1_0_1_2_0_13.html" in parsed.page_urls


@pytest.mark.parametrize("html", [
    '<html><meta http-equiv="refresh" content="0.1;url=https://service.zol.com.cn/checking"></html>',
    page("结构改变但不是空列表"),
    page("验证", title="访问验证"),
])
def test_invalid_or_verification_list_is_never_a_successful_empty_page(html):
    with pytest.raises(PageValidationError):
        parse_listing(html)


def test_unknown_reference_price_does_not_become_shop_price():
    html = page('<div class="list-item" data-follow-id="p100">'
                '<h3><a href="/cell_phone/index100.shtml">手机</a></h3>'
                '<a class="itemsub-b2c">￥4599</a></div>')
    assert parse_listing(html).phones[0]["price"] is None


def test_empty_reference_price_is_unknown():
    assert parse_listing(page(listed(price=""))).phones[0]["price"] is None


def test_series_reads_all_rendered_capacity_pages_and_marks_availability():
    rows = ""
    for identifier, css, availability in [("100", "model_page_1", "2家在售电商"), ("101", "model_page_2", "停产")]:
        rows += (
            f'<tr class="model__item {css}"><td class="cell-7">'
            f'<a href="/cell_phone/index{identifier}.shtml">手机{identifier}</a></td>'
            f'<td><a href="/100/{identifier}/param.shtml">参数</a>{availability}</td></tr>'
        )
    parsed = parse_series(page(rows), BASE_URL + "/series/57/123_1.html")
    assert [phone["id"] for phone in parsed.phones] == ["100", "101"]
    assert [phone["availability"] for phone in parsed.phones] == ["listed", "historical"]


def test_parameters_preserve_raw_values_and_brand():
    parsed = parse_parameters(parameters(), BASE_URL + "/100/100/param.shtml")
    assert parsed["brand"] == "小米"
    assert parsed["specs"]["电池容量"] == "6000mAh"
    assert parsed["specs"]["电商报价"] == "￥4599"
    assert all("纠错" not in value for value in parsed["specs"].values())


def test_parameters_reject_redirected_product_identity():
    with pytest.raises(PageValidationError, match="产品ID"):
        parse_parameters(parameters("999"), BASE_URL + "/100/100/param.shtml")


def test_product_uses_actual_parameter_and_series_links():
    parsed = parse_product(page(
        '<div class="product-nav"><a href="/100/100/param.shtml">参数</a></div>'
        '<a id="product_series_link" href="/series/57/123_1.html">系列共2款</a>'
    ), BASE_URL + "/cell_phone/index100.shtml")
    assert parsed["series_url"] == BASE_URL + "/series/57/123_1.html"
    assert parsed["param_url"] == BASE_URL + "/100/100/param.shtml"


class MemoryStorage:
    def __init__(self, fail_id=None):
        self.records = {}
        self.fail_id = fail_id

    def upsert_raw(self, raw):
        if raw["id"] == self.fail_id:
            raise sqlite3.OperationalError("写入失败测试")
        self.records[raw["id"]] = raw
        return raw

    def get_phone(self, identifier):
        return self.records.get(identifier)

def install_fake_crawler(monkeypatch, responses, metadata=None, requested=None):
    monkeypatch.setattr(pipeline, "_collect_official", lambda *_args: {"discovered": 0, "imported": 0, "errors": [], "coverage": {}})
    class FakeCrawler:
        def __init__(self, directory, delay):
            self.requests = 0
            self.cache_hits = 0

        def fetch(self, url, refresh=False):
            self.requests += 1
            if requested is not None:
                requested.append(url)
            return responses[url]

        def metadata(self, url):
            return {"fetched_at": (metadata or {}).get(url, "2020-01-01T00:00:00+00:00")}

        def close(self):
            pass

    monkeypatch.setattr(pipeline, "ZolCrawler", FakeCrawler)


def pipeline_responses():
    responses = {LIST_URL: page(listed("100") + listed("101") + '<div class="total">共 2 款</div>')}
    for identifier in ["100", "101"]:
        responses[BASE_URL + f"/cell_phone/index{identifier}.shtml"] = page(
            f'<div class="product-nav"><a href="/100/{identifier}/param.shtml">参数</a></div>'
        )
        responses[BASE_URL + f"/100/{identifier}/param.shtml"] = parameters(identifier)
    return responses


def test_sync_keeps_good_records_and_resumes_failed_detail(monkeypatch, tmp_path):
    responses = pipeline_responses()
    broken_url = BASE_URL + "/100/101/param.shtml"
    responses[broken_url] = page("参数结构失效")
    install_fake_crawler(monkeypatch, responses)
    storage = MemoryStorage()

    first = pipeline.run_sync(storage=storage, data_dir=tmp_path)

    assert first["status"] == "partial"
    assert first["completed"] == 1
    assert first["failed"] == 1
    assert set(storage.records) == {"100"}
    responses[broken_url] = parameters("101")

    second = pipeline.run_sync(storage=storage, data_dir=tmp_path)

    assert second["run_id"] == first["run_id"]
    assert second["status"] == "complete"
    assert second["completed"] == 2
    assert second["failed"] == 0
    assert second["failed_attempts"] == 1
    assert second["warnings"][0]["resolution"] == "后续请求/发布成功"
    assert set(storage.records) == {"100", "101"}
    assert json.loads((tmp_path / "reports/latest_sync.json").read_text(encoding="utf-8"))["completed"] == 2


def test_publish_failure_does_not_cancel_other_phone(monkeypatch, tmp_path):
    install_fake_crawler(monkeypatch, pipeline_responses())
    storage = MemoryStorage(fail_id="100")

    report = pipeline.run_sync(storage=storage, data_dir=tmp_path)

    assert report["status"] == "partial"
    assert report["completed"] == 2
    assert report["imported"] == 1
    assert set(storage.records) == {"101"}
    assert report["errors"][0]["stage"] == "publish"


def test_sync_lock_rejects_concurrent_process_without_waiting(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    with FileLock(reports / "sync.lock"):
        with pytest.raises(RuntimeError, match="已有手机数据同步任务"):
            pipeline.run_sync(storage=MemoryStorage(), data_dir=tmp_path)


def test_inconsistent_source_count_does_not_claim_complete(monkeypatch, tmp_path):
    responses = pipeline_responses()
    responses[LIST_URL] = responses[LIST_URL].replace("共 2 款", "共 3 款")
    install_fake_crawler(monkeypatch, responses)

    report = pipeline.run_sync(storage=MemoryStorage(), data_dir=tmp_path)

    assert report["completed"] == 2
    assert report["failed"] == 0
    assert report["status"] == "partial"
    assert report["list_count_mismatch"] is True


def test_variant_without_parameter_link_is_resolved_via_its_product_page(monkeypatch, tmp_path):
    responses = pipeline_responses()
    series_url = BASE_URL + "/series/57/123_1.html"
    responses[BASE_URL + "/cell_phone/index100.shtml"] = page(
        '<div class="product-nav"><a href="/100/100/param.shtml">参数</a></div>'
        '<a id="product_series_link" href="/series/57/123_1.html">系列</a>'
    )
    responses[series_url] = page(
        '<tr class="model__item"><td class="cell-7">'
        '<a href="/cell_phone/index102.shtml">手机另一容量版</a></td></tr>'
    )
    responses[BASE_URL + "/cell_phone/index102.shtml"] = page(
        '<div class="product-nav"><a href="/100/102/param.shtml">参数</a></div>'
    )
    responses[BASE_URL + "/100/102/param.shtml"] = parameters("102")
    install_fake_crawler(monkeypatch, responses)
    storage = MemoryStorage()

    report = pipeline.run_sync(storage=storage, data_dir=tmp_path)

    assert report["completed"] == 3
    assert report["failed"] == 0
    assert set(storage.records) == {"100", "101", "102"}


def test_cached_response_keeps_original_fetch_time(monkeypatch, tmp_path):
    requested = []
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: (requested.append(str(request.url)) or httpx.Response(200, text=page(listed())))
    ))
    monkeypatch.setattr(crawler, "utc_now", lambda: "2020-01-01T00:00:00+00:00")
    worker = crawler.ZolCrawler(tmp_path, client=client)
    worker.fetch(LIST_URL)
    monkeypatch.setattr(crawler, "utc_now", lambda: "2026-10-03T00:00:00+00:00")
    worker.fetch(LIST_URL)

    assert worker.metadata(LIST_URL)["fetched_at"] == "2020-01-01T00:00:00+00:00"
    assert len(requested) == 1
    assert worker.cache_hits == 1
    client.close()


def test_resume_preserves_old_details_and_independent_price_timestamp(monkeypatch, tmp_path):
    responses = pipeline_responses()
    broken_url = BASE_URL + "/100/101/param.shtml"
    responses[broken_url] = page("参数结构失效")
    times = {LIST_URL: "2019-01-01T00:00:00+00:00"}
    install_fake_crawler(monkeypatch, responses, times)
    storage = MemoryStorage()
    pipeline.run_sync(storage=storage, data_dir=tmp_path)
    monkeypatch.setattr(pipeline, "utc_now", lambda: "2026-10-03T00:00:00+00:00")
    responses[broken_url] = parameters("101")
    times[broken_url] = "2026-10-02T00:00:00+00:00"

    pipeline.run_sync(storage=storage, data_dir=tmp_path)

    assert storage.records["100"]["fetched_at"] == "2020-01-01T00:00:00+00:00"
    assert storage.records["100"]["specs_fetched_at"] == "2020-01-01T00:00:00+00:00"
    assert storage.records["100"]["price_fetched_at"] == "2019-01-01T00:00:00+00:00"
    assert storage.records["101"]["fetched_at"] == "2026-10-02T00:00:00+00:00"
    assert storage.records["101"]["price_fetched_at"] == "2019-01-01T00:00:00+00:00"


def series_row(identifier="100", availability="", price=""):
    return (f'<tr class="model__item"><td class="cell-7">'
            f'<a href="/cell_phone/index{identifier}.shtml">手机{identifier}</a></td>'
            f'<td class="cell-2"><span class="price">{price}</span></td>'
            f'<td><a href="/100/{identifier}/param.shtml">参数</a>{availability}</td></tr>')


def test_series_shortfall_is_partial_even_when_all_discovered_details_succeed(monkeypatch, tmp_path):
    responses = pipeline_responses()
    series_url = BASE_URL + "/series/57/123_1.html"
    responses[BASE_URL + "/cell_phone/index100.shtml"] = page(
        '<div class="product-nav"><a href="/100/100/param.shtml">参数</a></div>'
        f'<a id="product_series_link" href="{series_url}">系列</a>'
    )
    responses[series_url] = page(series_row() + "共有3款产品")
    install_fake_crawler(monkeypatch, responses)

    result = pipeline.run_sync(storage=MemoryStorage(), data_dir=tmp_path)

    assert result["completed"] == 2
    assert result["failed"] == 0
    assert result["status"] == "partial"
    assert result["series_count_discrepancies"][0]["visible_members"] == 1
    assert result["series_count_discrepancies"][0]["advertised_members"] == [3]


def test_series_count_is_aggregated_across_actual_pages(monkeypatch, tmp_path):
    responses = pipeline_responses()
    first = BASE_URL + "/series/57/123_1.html"
    second = BASE_URL + "/series/57/123_2.html"
    responses[BASE_URL + "/cell_phone/index100.shtml"] = page(
        '<div class="product-nav"><a href="/100/100/param.shtml">参数</a></div>'
        f'<a id="product_series_link" href="{first}">系列</a>'
    )
    responses[first] = page(series_row("100") + f'共有2款产品<div class="pagebar"><a href="{second}">2</a></div>')
    responses[second] = page(series_row("101") + "共有2款产品")
    install_fake_crawler(monkeypatch, responses)

    result = pipeline.run_sync(storage=MemoryStorage(), data_dir=tmp_path)

    assert result["status"] == "complete"
    assert result["series_count_discrepancies"] == []


def test_explicit_discontinued_price_and_series_override_listed_status(monkeypatch, tmp_path):
    responses = pipeline_responses()
    responses[LIST_URL] = page(listed("100", price="停产") + listed("101") + '<div class="total">共 2 款</div>')
    series_url = BASE_URL + "/series/57/123_1.html"
    responses[BASE_URL + "/cell_phone/index100.shtml"] = page(
        '<div class="product-nav"><a href="/100/100/param.shtml">参数</a></div>'
        f'<a id="product_series_link" href="{series_url}">系列</a>'
    )
    responses[series_url] = page(series_row("101", availability="停产"))
    install_fake_crawler(monkeypatch, responses)
    storage = MemoryStorage()

    pipeline.run_sync(storage=storage, data_dir=tmp_path)

    assert storage.records["100"]["availability"] == "historical"
    assert storage.records["101"]["availability"] == "historical"


def test_offline_repair_uses_metadata_and_retains_original_snapshot(monkeypatch, tmp_path):
    responses = pipeline_responses()
    install_fake_crawler(monkeypatch, responses)
    storage = MemoryStorage()
    result = pipeline.run_sync(storage=storage, data_dir=tmp_path)
    run_dir = tmp_path / "raw" / ("zol-sync-" + result["run_id"])
    checkpoint_path = run_dir / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    for raw in checkpoint["completed_records"].values():
        raw.pop("specs_fetched_at")
        raw.pop("price_fetched_at")
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
    html_dir = run_dir / "html"
    html_dir.mkdir()
    for url, response in responses.items():
        key = hashlib.sha256(url.encode()).hexdigest()[:20]
        (html_dir / f"{key}.html").write_text(response, encoding="utf-8")
        (html_dir / f"{key}.json").write_text(json.dumps({"fetched_at": "2018-01-01T00:00:00+00:00"}), encoding="utf-8")
    snapshot_count = len((run_dir / "phones.jsonl").read_text(encoding="utf-8").splitlines())
    monkeypatch.setattr(crawler.ZolCrawler, "fetch", lambda *_args, **_kwargs: pytest.fail("离线修复不得联网"))

    repaired = pipeline.repair_cached_provenance(storage=storage, data_dir=tmp_path)

    assert repaired["provenance_repaired"] == 2
    assert storage.records["100"]["fetched_at"] == "2018-01-01T00:00:00+00:00"
    assert storage.records["100"]["_corrects_fetched_at"] == "2020-01-01T00:00:00+00:00"
    assert len((run_dir / "phones.jsonl").read_text(encoding="utf-8").splitlines()) == snapshot_count + 2


def test_existing_response_times_are_not_replaced_by_later_cache_metadata():
    raw = {
        "fetched_at": "2020-01-01T00:00:00+00:00", "specs_fetched_at": "2020-01-01T00:00:00+00:00",
        "specs_source_url": BASE_URL + "/100/100/param.shtml",
        "price_fetched_at": "2019-01-01T00:00:00+00:00", "price_source_url": LIST_URL,
    }
    corrected = pipeline._correct_provenance(raw, lambda url: {"fetched_at": "2026-10-03T00:00:00+00:00"})
    assert corrected == raw


def test_unknown_cache_response_time_remains_unknown():
    raw = {"specs_source_url": BASE_URL + "/100/100/param.shtml", "price_source_url": LIST_URL}
    corrected = pipeline._correct_provenance(raw, lambda url: {})
    assert corrected["fetched_at"] is None
    assert corrected["specs_fetched_at"] is None
    assert corrected["price_fetched_at"] is None


def test_series_price_and_its_source_move_together(monkeypatch, tmp_path):
    responses = pipeline_responses()
    responses[LIST_URL] = responses[LIST_URL].replace("price price-normal", "unknown-price")
    series_url = BASE_URL + "/series/57/123_1.html"
    responses[BASE_URL + "/cell_phone/index100.shtml"] = page(
        '<div class="product-nav"><a href="/100/100/param.shtml">参数</a></div>'
        f'<a id="product_series_link" href="{series_url}">系列</a>'
    )
    responses[series_url] = page(series_row("100", price="￥3999"))
    install_fake_crawler(monkeypatch, responses, {series_url: "2019-01-01T00:00:00+00:00"})
    storage = MemoryStorage()

    pipeline.run_sync(storage=storage, data_dir=tmp_path)

    assert storage.records["100"]["price"] == "￥3999"
    assert storage.records["100"]["price_source_url"] == series_url
    assert storage.records["100"]["price_fetched_at"] == "2019-01-01T00:00:00+00:00"


def test_successful_grid_page_resolves_only_equivalent_list_route():
    covered = BASE_URL + "/cell_phone_index/subcate57_0_list_1_0_1_2_0_2.html"
    old_list = BASE_URL + "/cell_phone_index/subcate57_0_list_1_0_1_1_0_2.html"
    different_sort = BASE_URL + "/cell_phone_index/subcate57_0_list_1_0_9_1_0_2.html"
    checkpoint = {"list_pages": {covered: {}}, "errors": [
        {"stage": "list", "url": old_list}, {"stage": "list", "url": different_sort},
    ], "resolved_errors": []}

    pipeline._resolve_alternative_layouts(checkpoint)

    assert checkpoint["errors"] == [{"stage": "list", "url": different_sort}]
    assert checkpoint["resolved_errors"][0]["url"] == old_list


def comparison(identifier="102", *, broken_width=False):
    model = f'<tr><th>型号</th><td class="pro_name"><a href="/cell_phone/index{identifier}.shtml">小米另一个容量版</a></td></tr>'
    rows = ''.join(f'<tr><th>{key}</th><td>{value}</td></tr>' for key, value in {
        'CPU型号':'骁龙8 Elite', '电池容量':'6000mAh', '有线充电':'90W',
        '运行内存':'12GB', '机身内存':'512GB',
    }.items())
    if broken_width:
        rows += '<tr><th>屏幕尺寸</th><td>6.7</td><td>错位</td></tr>'
    return page('<div class="breadcrumb"><a href="/cell_phone_index/subcate57_80_list_1.html">小米手机</a></div>'
                '<table class="series_param_detail">' + model
                + '<tr><th>价格/商家</th><td><div class="price_td"><span class="price">￥3999</span><p>2商家在售</p></div></td></tr>'
                + '<tr><th></th><td>无参数名的原始单元格</td></tr>' + rows + '</table>')


def test_comparison_uses_real_model_columns_and_reference_prices():
    url = BASE_URL + '/series/57/80/param_123_0_1.html'
    parsed = parse_series_parameters(comparison(), url)
    assert parsed.phones[0]['id'] == '102'
    assert parsed.phones[0]['price'] == '￥3999'
    assert parsed.phones[0]['brand'] == '小米'
    assert parsed.phones[0]['specs']['机身内存'] == '512GB'
    assert parsed.phones[0]['specs_source_url'] == url
    assert parsed.phones[0]['availability'] == 'listed'


def test_comparison_rejects_misaligned_parameter_columns():
    with pytest.raises(PageValidationError, match='列宽'):
        parse_series_parameters(comparison(broken_width=True), BASE_URL + '/series/57/80/param_123_0_1.html')


def test_sync_comparison_follows_real_total_link_and_publishes_complete_specs(monkeypatch, tmp_path):
    responses = pipeline_responses()
    series = BASE_URL + '/series/57/123_1.html'
    params = BASE_URL + '/series/57/80/param_123_0_1.html'
    responses[BASE_URL + '/cell_phone/index100.shtml'] = page(
        '<div class="product-nav"><a href="/100/100/param.shtml">参数</a></div>'
        f'<a id="product_series_link" href="{series}">系列</a>')
    responses[series] = page(series_row('100') + f'<a class="total" href="{params}">共有2款产品</a>')
    responses[params] = comparison()
    install_fake_crawler(monkeypatch, responses)
    storage = MemoryStorage()

    result = pipeline.run_sync(storage=storage, data_dir=tmp_path)

    assert result['status'] == 'complete'
    assert result['completed'] == 3
    assert result['series_comparison_pages'] == 1
    assert result['series_count_discrepancies'] == []
    assert storage.records['102']['specs_source_url'] == params
    assert storage.records['102']['fetched_at'] == storage.records['102']['specs_fetched_at']


def test_old_checkpoint_repair_cannot_override_later_actual_snapshot(monkeypatch, tmp_path):
    from phone_assistant.storage import Storage
    responses = pipeline_responses()
    install_fake_crawler(monkeypatch, responses)
    storage = Storage(tmp_path / 'phones.sqlite3')
    report = pipeline.run_sync(storage=storage, data_dir=tmp_path)
    run_dir = tmp_path / 'raw' / ('zol-sync-' + report['run_id'])
    checkpoint_path = run_dir / 'checkpoint.json'
    checkpoint = json.loads(checkpoint_path.read_text(encoding='utf-8'))
    old = checkpoint['completed_records']['100']
    newer = {**old, 'fetched_at':'2025-01-01T00:00:00+00:00',
             'specs_fetched_at':'2025-01-01T00:00:00+00:00', 'price_fetched_at':'2025-01-01T00:00:00+00:00',
             'price':'￥4999', 'specs':{**old['specs'], '电池容量':'7000mAh'}}
    storage.upsert_raw(newer)
    for raw in checkpoint['completed_records'].values():
        raw.pop('specs_fetched_at')
        raw.pop('price_fetched_at')
    checkpoint_path.write_text(json.dumps(checkpoint), encoding='utf-8')
    html_dir = run_dir / 'html'
    html_dir.mkdir()
    for url, response in responses.items():
        key = hashlib.sha256(url.encode()).hexdigest()[:20]
        (html_dir / f'{key}.html').write_text(response, encoding='utf-8')
        (html_dir / f'{key}.json').write_text(json.dumps({'fetched_at':'2018-01-01T00:00:00+00:00'}), encoding='utf-8')

    pipeline.repair_cached_provenance(storage=storage, data_dir=tmp_path)

    phone = storage.get_phone('100')
    assert phone['fetched_at'] == newer['fetched_at']
    assert phone['price'] == 4999
    assert phone['battery_mah'] == 7000
    assert phone['specs']['电池容量'] == '7000mAh'
    storage.reclean()
    assert storage.get_phone('100')['price'] == 4999


def new_module(identifier='300', heading='vivo手机新品', price='￥4999'):
    return (f'<div class="module"><div class="module-header"><h3>{heading}</h3></div>'
            '<ul class="rank-list"><li><a href="/cell_phone/index' + identifier
            + '.shtml" title="vivo 测试新品(12GB/512GB)">截断文字</a>'
            f'<em class="price">{price}</em></li></ul></div>')


def test_new_arrivals_are_independent_of_old_popularity_and_promotions():
    parsed = parse_discovery(page(listed('100') + new_module('300') + new_module('999', heading='猜你喜欢')))
    assert parsed.main_count == 1
    assert [raw['id'] for raw in parsed.phones] == ['300']
    assert parsed.phones[0]['name'] == 'vivo 测试新品(12GB/512GB)'
    assert parsed.phones[0]['new_from_source'] is True
    assert parsed.phones[0]['source_position'] == 1
    assert parsed.phones[0]['availability'] == 'unknown'


def test_brand_directory_follows_source_links_without_fixed_brand_ids():
    brand_url = BASE_URL + '/cell_phone_index/subcate57_999999_list_1.html'
    html = page('<ul class="manu normal"><li><a href="' + brand_url
                + '">Future（未来品牌）</a><a href="https://elsewhere.test/cell_phone_index/subcate57_12_list_1.html">外站</a></li></ul>',
                title='手机最新产品 手机品牌大全')
    assert parse_brand_directory(html, BASE_URL + '/category/57.html') == {'未来品牌': brand_url}


def test_latest_sync_publishes_new_models_and_variant_metadata_without_old_details(monkeypatch, tmp_path):
    brand_url = BASE_URL + '/cell_phone_index/subcate57_999999_list_1.html'
    series = BASE_URL + '/series/57/123_1.html'
    compare_url = BASE_URL + '/series/57/80/param_123_0_1.html'
    responses = {
        LIST_URL: page(listed('100') + '<div class="section"><div class="section-header"><h3>手机品牌报价大全</h3></div>'
                       f'<a href="{brand_url}">vivo手机</a></div>'),
        brand_url: page(listed('100') + new_module('300')),
        BASE_URL + '/cell_phone/index300.shtml': page('<div class="product-nav"><a href="/100/300/param.shtml">参数</a></div>'
                                                     f'<a id="product_series_link" href="{series}">系列</a>'),
        BASE_URL + '/100/300/param.shtml': parameters('300'),
        series: page(series_row('300') + f'<a class="total" href="{compare_url}">共有2款产品</a>'),
        compare_url: comparison('301'),
    }
    times = {brand_url:'2019-01-01T00:00:00+00:00', compare_url:'2022-01-01T00:00:00+00:00'}
    requested = []
    install_fake_crawler(monkeypatch, responses, times, requested)
    storage = MemoryStorage()

    report = pipeline.run_sync(storage=storage, data_dir=tmp_path, latest_only=True)

    assert report['completed'] == 2
    assert set(storage.records) == {'300','301'}
    assert BASE_URL + '/cell_phone/index100.shtml' not in requested
    assert storage.records['301']['new_from_source'] is True
    assert storage.records['301']['new_release_catalog_url'] == brand_url
    assert storage.records['301']['catalog_fetched_at'] == times[brand_url]
    assert storage.records['301']['specs_fetched_at'] == times[compare_url]
    assert report['brand_coverage']['vivo']['new_completed'] == 1
    assert report['brand_coverage']['vivo']['main_discovered'] == 1


def test_official_model_counts_and_pending_are_separate_from_sku_completion(monkeypatch, tmp_path):
    install_fake_crawler(monkeypatch, pipeline_responses())
    monkeypatch.setattr(pipeline, '_collect_official', lambda *_args: {
        'discovered':1, 'records_discovered':3, 'imported':3, 'pending':2,
        'errors':[], 'coverage':{'apple':{'pending':2}}, 'raws':[],
    })
    report = pipeline.run_sync(storage=MemoryStorage(), data_dir=tmp_path)
    assert report['discovered'] == 5
    assert report['completed'] == 5
    assert report['official_models_discovered'] == 1
    assert report['official_pending'] == 2
    assert report['status'] == 'partial'
    assert 'raws' not in json.loads((tmp_path/'reports/latest_sync.json').read_text(encoding='utf-8'))


def test_offline_official_merge_is_idempotent_and_uses_original_times(monkeypatch, tmp_path):
    install_fake_crawler(monkeypatch, pipeline_responses())
    storage = MemoryStorage()
    pipeline.run_sync(storage=storage, data_dir=tmp_path)
    official_raw = {'id':'official:apple:test', 'name':'Apple测试新机', 'brand':'苹果',
                    'origin':'official', 'specs':{}, 'fetched_at':'2019-01-01T00:00:00+00:00'}
    path = tmp_path/'official.json'
    path.write_text(json.dumps({'raws':[official_raw], 'discovered':2, 'models_discovered':2,
                               'imported':1,'errors':[], 'coverage':{'apple':{'pending':1}}}),encoding='utf-8')
    first = pipeline.merge_official_report(path,data_dir=tmp_path)
    second = pipeline.merge_official_report(path,data_dir=tmp_path)
    assert first['discovered'] == second['discovered'] == 3
    assert second['official_pending'] == 1
    assert second['status'] == 'partial'
    assert set(storage.records) == {'100','101'}
    assert json.loads(path.read_text(encoding='utf-8'))['raws'][0]['fetched_at'] == official_raw['fetched_at']


def test_exact_catalog_quote_survives_unpriced_comparison(monkeypatch,tmp_path):
    responses=pipeline_responses()
    series=BASE_URL+'/series/57/123_1.html'
    compare_url=BASE_URL+'/series/57/80/param_123_0_1.html'
    responses[BASE_URL+'/cell_phone/index100.shtml']=page('<div class="product-nav"><a href="/100/100/param.shtml">参数</a></div>'
                                                        f'<a id="product_series_link" href="{series}">系列</a>')
    responses[series]=page(series_row('100')+f'<a class="total" href="{compare_url}">共有1款产品</a>')
    responses[compare_url]=comparison('100').replace('￥3999','即将上市')
    install_fake_crawler(monkeypatch,responses)
    storage=MemoryStorage()
    pipeline.run_sync(storage=storage,data_dir=tmp_path)
    assert storage.records['100']['price']=='￥4399'
    assert storage.records['100']['price_source_url']==LIST_URL
    assert storage.records['100']['price_fetched_at']=='2020-01-01T00:00:00+00:00'
