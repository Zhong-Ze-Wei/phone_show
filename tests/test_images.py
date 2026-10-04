from hashlib import sha256
import json
import sqlite3

from bs4 import BeautifulSoup

from phone_assistant.images import IMAGE_FIELDS, image_record, preferred_image, replay_cached_images, zol_primary_image
from phone_assistant.official_sources import parse_specifications
from phone_assistant.storage import Storage


CAPTURED = "2026-10-03T07:42:34.255734+00:00"
PRODUCT = "https://detail.zol.com.cn/cell_phone/index100.shtml"
THUMB = "https://2a.zol-img.com.cn/product/274_80x60/542/phone.png"
PRIMARY = "https://2a.zol-img.com.cn/product/274_320x240/542/phone.png"


def save_cache(raw_dir, url, html, *, official=False, final_url=None):
    folder = raw_dir / ("official/unit" if official else "zol-sync-unit/html")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (sha256(url.encode()).hexdigest()[:20] + ".html")
    path.write_text(html, encoding="utf-8")
    path.with_suffix(".json").write_text(json.dumps({"url": url, "source_url": final_url or url,
        "status": 200, "fetched_at": CAPTURED}), encoding="utf-8")
    return path


def zol_page(body):
    return "<title>小米测试手机-ZOL中关村在线</title>" + body


def base_raw(**fields):
    return {"id": "100", "name": "小米测试手机(12GB/256GB)", "brand": "小米", "price": 3000,
        "origin": "zol", "fetched_at": CAPTURED, "source_url": PRODUCT,
        "availability": "listed", "new_from_source": True, "image_url": THUMB, "image_role": "thumbnail",
        "specs": {"RAM容量": "12GB", "ROM容量": "256GB", "电池容量": "6000mAh"}, **fields}


def without_images(record):
    result = {key: value for key, value in record.items() if key not in IMAGE_FIELDS}
    result["field_sources"] = {key: value for key, value in record.get("field_sources", {}).items() if key != "image_url"}
    return result


def test_product_primary_uses_actual_src_and_never_picks_neighbor_or_logo():
    soup = BeautifulSoup(zol_page(f'''
    <div class="big-pic"><a href="/picture_index_2744/index123_0_p999.shtml"><img src="https://example.com/neighbor.png"></a></div>
    <div class="big-pic"><a href="/picture_index_2744/index123_0_p100.shtml"><img src="{PRIMARY}" width="320" height="240"></a></div>
    <img src="https://example.com/logo.png">'''), "html.parser")
    record = zol_primary_image(soup, PRODUCT)
    assert record["image_url"] == PRIMARY
    assert record["image_width"] == 320
    assert record["image_source_url"] == PRODUCT
    assert image_record(BeautifulSoup('<img src="https://example.com/logo.png">', "html.parser").img, PRODUCT, "catalog") == {}


def test_parameter_card_image_requires_current_product_link():
    soup = BeautifulSoup(f'<div class="goods-card__pic"><a href="/cell_phone/index999.shtml"><img src="{PRIMARY}"></a></div>', "html.parser")
    assert zol_primary_image(soup, "https://detail.zol.com.cn/100/100/param.shtml") == {}


def test_larger_declared_primary_is_kept_over_thumbnail_and_smaller_primary():
    current = {"image_url": PRIMARY, "image_role": "primary", "image_width": 320, "image_height": 240}
    assert preferred_image(current, {"image_url": THUMB, "image_role": "thumbnail"}) == current
    assert preferred_image(current, {"image_url": "https://example.com/param.jpg", "image_role": "primary", "image_width": 260, "image_height": 195}) == current


def test_verified_vivo_product_color_image_overrides_catalog_without_invented_dimensions():
    html = '''<title>vivo X500 专业影像旗舰 - vivo官方网站</title>
    <div class="color-image-list"><li class="color-image-item"><img src="https://example.com/x500.png" alt="vivo (晴天)"></li></div>
    <li class="parameter-item"><h2 class="parameter-title">存储</h2><li class="attr-item">
    <p class="attr-item-name">运行内存（RAM）</p><div class="attr-item-text">12GB</div></li></li>'''
    raw = parse_specifications(html, "https://www.vivo.com/vivo/param/x500", "vivo", fetched_at=CAPTURED,
        model={"image_url": "https://example.com/catalog.jpg"})[0]
    assert raw["image_url"] == "https://example.com/x500.png"
    assert raw["image_role"] == "primary"
    assert raw["image_fetched_at"] == CAPTURED
    assert "image_width" not in raw


def test_image_replay_preserves_all_other_fields_and_raw_snapshots_then_survives_reclean(tmp_path):
    storage = Storage(tmp_path / "phones.sqlite3")
    storage.upsert_raw(base_raw())
    original = storage.get_phone("100")
    with sqlite3.connect(storage.path) as connection:
        raw_before = connection.execute("SELECT raw_json FROM raw_snapshots").fetchall()
        db_updated_before = connection.execute("SELECT updated_at FROM phones").fetchall()
    raw_dir = tmp_path / "raw"
    path = save_cache(raw_dir, PRODUCT, zol_page(f'<div class="big-pic"><a href="/picture_index_2744/index123_0_p100.shtml"><img src="{PRIMARY}" width="320" height="240"></a></div>'))
    preview = replay_cached_images(storage.path, raw_dir)
    assert preview["would_patch"] == 1
    assert storage.get_phone("100") == original
    applied = replay_cached_images(storage.path, raw_dir, apply=True)
    updated = storage.get_phone("100")
    assert applied["patched"] == 1
    assert applied["changes"][0]["cache_path"] == str(path)
    assert updated["image_url"] == PRIMARY
    assert updated["field_sources"]["image_url"]["fetched_at"] == CAPTURED
    assert without_images(updated) == without_images(original)
    with sqlite3.connect(storage.path) as connection:
        assert connection.execute("SELECT raw_json FROM raw_snapshots").fetchall() == raw_before
        assert connection.execute("SELECT updated_at FROM phones").fetchall() == db_updated_before
    assert replay_cached_images(storage.path, raw_dir)["would_patch"] == 0
    storage.reclean()
    assert storage.get_phone("100") == updated
    assert replay_cached_images(storage.path, raw_dir)["would_patch"] == 0
    storage.upsert_raw(base_raw(price=2800, fetched_at="2026-10-04T09:00:00+00:00"))
    assert storage.get_phone("100")["image_url"] == PRIMARY
    assert storage.get_phone("100")["price"] == 2800


def test_replay_rejects_redirected_cache_and_preserves_unverified_original(tmp_path):
    storage = Storage(tmp_path / "phones.sqlite3")
    storage.upsert_raw(base_raw())
    raw_dir = tmp_path / "raw"
    save_cache(raw_dir, PRODUCT, zol_page(f'<div class="big-pic"><a href="/picture_index_2744/index123_0_p100.shtml"><img src="{PRIMARY}"></a></div>'),
        final_url="https://detail.zol.com.cn/cell_phone/index999.shtml")
    assert replay_cached_images(storage.path, raw_dir, apply=True)["patched"] == 0
    assert storage.get_phone("100")["image_url"] == THUMB


def test_official_color_image_only_shares_verified_exact_family_not_pro_model(tmp_path):
    storage = Storage(tmp_path / "phones.sqlite3")
    official_url = "https://www.vivo.com/vivo/param/x500"
    storage.upsert_raw(base_raw(id="official:vivo:x500", name="vivo X500", brand="vivo", origin="official",
        source_url="https://www.vivo.com/vivo/x500/", specs_source_url=official_url, platform="vivo", image_url=None))
    storage.upsert_raw(base_raw(id="base", name="vivo X500(12GB/512GB)", brand="vivo", source_url="https://detail.zol.com.cn/cell_phone/index101.shtml"))
    storage.upsert_raw(base_raw(id="pro", name="vivo X500 Pro(12GB/512GB)", brand="vivo", source_url="https://detail.zol.com.cn/cell_phone/index102.shtml"))
    raw_dir = tmp_path / "raw"
    save_cache(raw_dir, official_url, '''<title>vivo X500 专业影像旗舰 - vivo官方网站</title>
    <ul class="color-image-list"><li class="color-image-item"><img src="https://example.com/x500.png"></li></ul>
    <li class="parameter-item"><h2 class="parameter-title">存储</h2><li class="attr-item"><p class="attr-item-name">运行内存（RAM）</p><div class="attr-item-text">12GB</div></li></li>''', official=True)
    result = replay_cached_images(storage.path, raw_dir, apply=True)
    assert result["patched"] == 2
    assert storage.get_phone("base")["image_url"] == "https://example.com/x500.png"
    assert storage.get_phone("pro")["image_url"] == THUMB


def test_new_primary_from_later_real_source_supersedes_old_override(tmp_path):
    storage = Storage(tmp_path / "phones.sqlite3")
    storage.upsert_raw(base_raw())
    raw_dir = tmp_path / "raw"
    save_cache(raw_dir, PRODUCT, zol_page(f'<div class="big-pic"><a href="/picture_index_2744/index123_0_p100.shtml"><img src="{PRIMARY}" width="320" height="240"></a></div>'))
    replay_cached_images(storage.path, raw_dir, apply=True)
    storage.upsert_raw(base_raw(image_url="https://example.com/new-real-product.png", image_role="primary", image_width=320,
        image_height=240, image_source_url=PRODUCT, image_fetched_at="2026-10-04T09:00:00+00:00", fetched_at="2026-10-04T09:00:00+00:00"))
    assert storage.get_phone("100")["image_url"] == "https://example.com/new-real-product.png"
    storage.reclean()
    assert storage.get_phone("100")["image_url"] == "https://example.com/new-real-product.png"


def test_cache_parsing_concurrent_price_update_is_not_rolled_back_by_image_publish(tmp_path, monkeypatch):
    import phone_assistant.images as images

    storage = Storage(tmp_path / "phones.sqlite3")
    storage.upsert_raw(base_raw(price=3000))
    raw_dir = tmp_path / "raw"
    save_cache(raw_dir, PRODUCT, zol_page(f'<div class="big-pic"><a href="/picture_index_2744/index123_0_p100.shtml"><img src="{PRIMARY}" width="320" height="240"></a></div>'))
    real_soup = images.BeautifulSoup
    latest_time = "2026-10-04T09:00:00+00:00"

    def interleaved_parse(*arguments, **kwargs):
        storage.upsert_raw(base_raw(price=2800, fetched_at=latest_time))
        return real_soup(*arguments, **kwargs)

    monkeypatch.setattr(images, "BeautifulSoup", interleaved_parse)
    result = replay_cached_images(storage.path, raw_dir, apply=True)
    current = storage.get_phone("100")
    assert result["patched"] == 1
    assert current["image_url"] == PRIMARY
    assert current["price"] == 2800
    assert current["fetched_at"] == latest_time
    storage.reclean()
    assert storage.get_phone("100")["image_url"] == PRIMARY
    assert storage.get_phone("100")["price"] == 2800
