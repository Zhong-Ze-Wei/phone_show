import json

import httpx
import pytest
from bs4 import BeautifulSoup

from phone_assistant import official_sources as official
from phone_assistant.cleaning import clean_phone


TIME = "2026-10-04T08:00:00+00:00"


def vivo_section(title, values):
    return '<li class="parameter-item"><h2 class="parameter-title">' + title + '</h2>' + ''.join(
        '<li class="attr-item"><p class="attr-item-name">' + key + '</p><div class="attr-item-text">' + value + '</div></li>'
        for key, value in values.items()) + '</li>'


def test_vivo_discovers_public_ssr_banner_without_hardcoded_model():
    payload = [{"pcUrl": 1, "mainTitle": 2, "bannerName": 3},
               "https://www.vivo.com.cn/vivo/x900promax/", "vivo X900 Pro Max", "X900新品发布"]
    html = '<script type="application/json">' + json.dumps(payload) + '</script>'
    models = official.discover_models(html, official.CATALOGS['vivo'], 'vivo')
    assert models[0]['url'].endswith('/x900promax/')
    assert models[0]['new_from_source'] is True


def test_catalog_only_discovers_real_phone_links_and_local_badges():
    html = '''<ul><li><a href="/iphone-duo/">iPhone Duo<span class="badge-new">新款</span></a></li>
    <li><a href="/iphone-17/">iPhone 17</a></li></ul>
    <a href="https://evil.example/iphone-18/">Fake</a>
    <a href="/ipad/">iPad</a><a href="/iphone-18-pro/specs/">规格</a>'''
    models = official.discover_models(html, official.CATALOGS['apple'], 'apple')
    assert len(models) == 3
    assert [model['new_from_source'] for model in models] == [True, False, False]
    assert models[1]['source_position'] == 1
    assert models[2]['specs_url'] == 'https://www.apple.com.cn/iphone-18-pro/specs/'


@pytest.mark.parametrize('links', [
    '<a href="/iphone-16/">iPhone 16</a><a href="/iphone-16/specs/">技术规格</a>',
    '<a href="/iphone-16/specs/">技术规格</a><a href="/iphone-16/">iPhone 16</a>',
])
def test_apple_specification_and_landing_links_are_one_real_model(links):
    models = official.discover_models(links, official.CATALOGS['apple'], 'apple')
    assert len(models) == 1
    assert models[0]['url'] in {'https://www.apple.com.cn/iphone-16/',
                                'https://www.apple.com.cn/iphone-16/specs/'}
    assert models[0]['specs_url'] == 'https://www.apple.com.cn/iphone-16/specs/'
    assert models[0]['new_from_source'] is False


def test_apple_direct_specs_link_retains_host_and_path_validation():
    html = '''<a href="/iphone-16/specs/">进一步了解</a>
    <a href="https://evil.example/iphone-16/specs/">假链接</a>
    <a href="/iphone-16/specs/extra/">不是规格页</a>
    <a href="/ipad/specs/">不是手机</a>'''
    models = official.discover_models(html, official.CATALOGS['apple'], 'apple')
    assert [model['url'] for model in models] == ['https://www.apple.com.cn/iphone-16/specs/']


def test_honor_explicit_latest_section_and_expired_badge():
    html = '''<div data-series="latest"><a href="/cn/phones/honor-magic9/">荣耀Magic9</a></div>
    <a href="/cn/phones/honor-90/"><span class="new_product" data-off-time="1">New</span>荣耀90</a>'''
    models = official.discover_models(html, official.CATALOGS['honor'], 'honor')
    assert [model['new_from_source'] for model in models] == [True, False]


def test_vivo_prices_are_separate_verified_skus_not_cross_product():
    html = '<title>vivo X500 专业影像旗舰 - vivo官方网站</title>' + vivo_section('建议零售价', {
        '': 'vivo X500（12GB+256GB）：5499.00元 vivo X500（16GB+1TB）：6999.00元'
    }) + vivo_section('上市时间', {'': '2026年9月'}) + vivo_section('处理器', {'CPU型号': '天玑9600M'})
    raws = official.parse_specifications(html, 'https://www.vivo.com.cn/vivo/param/x500', 'vivo', fetched_at=TIME)
    assert len(raws) == 2
    assert raws[0]['price'] == '5499.00'
    assert raws[1]['specs']['运行内存RAM容量(GB)'] == '16GB'
    assert raws[1]['specs']['机身存储ROM容量(GB)'] == '1TB'
    assert raws[0]['price_kind'] == 'official_msrp'
    assert raws[0]['specs']['上市日期'] == '2026年9月'
    assert raws[0]['origin'] == 'official'
    assert raws[0]['id'] != raws[1]['id']


def test_price_from_never_becomes_specific_variant_price_or_release_year():
    html = '<title>vivo X900</title>' + vivo_section('存储', {'运行内存（RAM）': '12GB/16GB'}) + '<footer>Copyright2026</footer>'
    raws = official.parse_specifications(html, 'https://www.vivo.com.cn/vivo/param/x900', 'vivo', fetched_at=TIME,
                                        catalog_url=official.CATALOGS['vivo'], model={'price_from': '5999', 'catalog_fetched_at': TIME})
    assert len(raws) == 1
    assert raws[0]['price'] is None
    assert raws[0]['price_from'] == '5999'
    assert '上市日期' not in raws[0]['specs']
    assert raws[0]['catalog_fetched_at'] == TIME


def test_honor_reads_public_data_attributes_and_preserves_notes():
    html = '''<title>荣耀Magic9参数配置-规格性能 | 荣耀官方网站</title>
    <div class="products-spec-component-list-item-right-item-list-item"><h3>电池容量</h3>
    <div data-value="8000mAh（典型值）"></div><div data-value="额定7820mAh"></div></div>'''
    raw = official.parse_specifications(html, 'https://www.honor.com/cn/phones/honor-magic9/spec/', 'honor', fetched_at=TIME)[0]
    assert raw['name'] == '荣耀Magic9'
    assert raw['specs']['电池容量'] == '8000mAh（典型值）\n额定7820mAh'


def test_huawei_parent_headings_separate_display_and_body_dimensions():
    html = '''<h1>HUAWEI Mate 90 规格参数</h1>
    <li class="large-accordion__item"><span class="large-accordion__title">屏幕</span>
    <div class="large-accordion__inner"><div class="large-accordion-subtitle">尺寸</div><p>6.75英寸</p></div></li>
    <li class="large-accordion__item"><span class="large-accordion__title">尺寸与重量</span>
    <div class="large-accordion__wrap"><div class="large-accordion-subtitle">厚度</div><p>7.95mm</p></div></li>'''
    raw = official.parse_specifications(html, 'https://consumer.huawei.com/cn/phones/mate90/specs/', 'huawei', fetched_at=TIME)[0]
    assert raw['specs']['屏幕尺寸'] == '6.75英寸'
    assert raw['specs']['机身厚度(毫米)'] == '7.95mm'
    assert raw['specs']['屏幕/尺寸'] == '6.75英寸'


def test_apple_pro_and_max_columns_stay_separate():
    html = '''<title>iPhone 18 Pro - 技术规格</title>
    <div class="techspecs-columnheader">iPhone 18 Pro</div><div class="techspecs-columnheader">iPhone 18 Pro Max</div>
    <div class="techspecs-row"><div class="techspecs-rowheader">尺寸与重量<sup>2</sup></div>
    <div class="techspecs-column">厚度：8.75毫米 重量：211克</div>
    <div class="techspecs-column">厚度：8.75毫米 重量：233克</div></div>
    <div class="techspecs-row"><div class="techspecs-rowheader">芯片</div><div class="techspecs-column">A20 Pro</div></div>'''
    raws = official.parse_specifications(html, 'https://www.apple.com.cn/iphone-18-pro/specs/', 'apple', fetched_at=TIME)
    assert len(raws) == 2
    assert raws[0]['specs']['机身重量(克)'] == '211克'
    assert raws[1]['specs']['机身重量(克)'] == '233克'
    assert raws[1]['specs']['芯片型号'] == 'A20 Pro'
    assert raws[0]['id'] != raws[1]['id']


def test_apple_explicit_operating_system_is_available_to_os_filter():
    html = '''<title>iPhone 17 - 技术规格</title>
    <div class="techspecs-row"><div class="techspecs-rowheader">操作系统</div>
    <div class="techspecs-column">iOS 移动操作系统</div></div>'''
    source = 'https://www.apple.com.cn/iphone-17/specs/'
    raw = official.parse_specifications(html, source, 'apple', fetched_at=TIME)[0]
    phone = clean_phone(raw)
    assert raw['specs']['操作系统'] == 'iOS 移动操作系统'
    assert phone['os_family'] == 'iOS'
    assert phone['specs_source_url'] == source
    assert phone['specs_fetched_at'] == TIME


def test_apple_brand_does_not_fill_missing_operating_system():
    html = '''<title>iPhone 17 - 技术规格</title>
    <div class="techspecs-row"><div class="techspecs-rowheader">芯片</div>
    <div class="techspecs-column">A19 芯片</div></div>'''
    raw = official.parse_specifications(html, 'https://www.apple.com.cn/iphone-17/specs/',
                                        'apple', fetched_at=TIME)[0]
    assert clean_phone(raw)['os_family'] is None


def test_oppo_camera_and_video_labels_do_not_merge():
    html = '''<h1>Find X10</h1>
    <div class="param-detail-item"><div class="item-left-heading"><span>相机</span></div>
    <div class="item-right-list"><p class="key"><span>后置</span></p><p class="value">2亿主摄</p></div></div>
    <div class="param-detail-item"><div class="item-left-heading"><span>视频</span></div>
    <div class="item-right-list"><p class="key"><span>后置</span></p><p class="value">4K 60fps</p></div></div>'''
    raw = official.parse_specifications(html, 'https://www.oppo.com/cn/smartphones/series-find-x/find-x10/specs/', 'oppo', fetched_at=TIME)[0]
    assert raw['name'] == 'OPPO Find X10'
    assert raw['specs']['相机/后置'] == '2亿主摄'
    assert raw['specs']['视频/后置'] == '4K 60fps'
    assert raw['specs']['摄像头像素'] == '2亿主摄'


def test_changed_specification_markup_fails_without_empty_record():
    with pytest.raises(ValueError, match='规格结构未识别'):
        official.parse_specifications('<title>荣耀Magic9</title><p>欢迎</p>', 'https://www.honor.com/cn/phones/honor-magic9/spec/', 'honor', fetched_at=TIME)


def install_transport(monkeypatch, pages):
    original = httpx.Client
    requested = []
    def handler(request):
        requested.append(str(request.url))
        content = pages.get(str(request.url))
        return httpx.Response(200 if content is not None else 404, text=content or 'missing')
    monkeypatch.setattr(official.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(official, '_utc', lambda: TIME)
    return requested


def test_sync_apple_direct_specs_page_without_guessing_landing_url(monkeypatch, tmp_path):
    catalog = official.CATALOGS['apple']
    specs = 'https://www.apple.com.cn/iphone-16/specs/'
    requested = install_transport(monkeypatch, {
        catalog: '<a href="/iphone-16/specs/">进一步了解</a>',
        specs: '<title>iPhone 16 - 技术规格</title><div class="techspecs-row">'
               '<div class="techspecs-rowheader">芯片</div>'
               '<div class="techspecs-column">A18 芯片</div></div>',
    })
    report = official.sync_official(brands=['apple'], delay=0, cache_dir=tmp_path)
    assert requested == [catalog, specs]
    assert report['errors'] == []
    assert report['coverage']['apple']['discovered'] == 1
    assert report['coverage']['apple']['collected'] == 1
    assert report['coverage']['apple']['models'][0]['specs_url'] == specs
    assert len(report['raws']) == 1
    raw = report['raws'][0]
    assert raw['name'] == 'iPhone 16'
    assert raw['source_url'] == raw['specs_source_url'] == specs
    assert raw['fetched_at'] == raw['catalog_fetched_at'] == TIME
    assert raw['current_source'] is True
    assert raw['new_from_source'] is False


def test_apple_plus_only_parsed_with_explicit_same_page_columns():
    html = '''<title>iPhone 16 - 技术规格</title>
    <div class="techspecs-columnheader">iPhone 16</div>
    <div class="techspecs-columnheader">iPhone 16 Plus</div>
    <div class="techspecs-row"><div class="techspecs-rowheader">尺寸与重量</div>
    <div class="techspecs-column">重量：170克</div>
    <div class="techspecs-column">重量：199克</div></div>'''
    raws = official.parse_specifications(html, 'https://www.apple.com.cn/iphone-16/specs/',
                                        'apple', fetched_at=TIME)
    assert [raw['name'] for raw in raws] == ['iPhone 16', 'iPhone 16 Plus']
    assert raws[0]['specs']['机身重量(克)'] == '170克'
    assert raws[1]['specs']['机身重量(克)'] == '199克'
    assert raws[0]['id'] != raws[1]['id']


def test_sync_cap_report_atomic_publish_and_true_source_times(monkeypatch, tmp_path):
    catalog = official.CATALOGS['vivo']
    landing = 'https://www.vivo.com.cn/vivo/x900/'
    specs = 'https://www.vivo.com.cn/vivo/param/x900'
    requested = install_transport(monkeypatch, {
        catalog: '<a href="/vivo/x900/">vivo X900</a><a href="/vivo/x901/">vivo X901</a>',
        landing: '<main>立即购买</main><a href="/vivo/param/x900">规格参数</a>',
        specs: '<title>vivo X900</title>' + vivo_section('处理器', {'CPU型号': '天玑9600'}),
    })
    class Storage:
        def __init__(self): self.received = []
        def import_many(self, raws): self.received.extend(raws)
    storage = Storage()
    report = official.sync_official(storage, brands=['vivo'], delay=0, cache_dir=tmp_path, max_per_brand=1)
    assert report['coverage']['vivo']['pending'] == 1
    assert report['coverage']['vivo']['collected'] == 1
    assert report['imported'] == 1
    assert storage.received[0]['catalog_fetched_at'] == TIME
    assert storage.received[0]['specs_source_url'] == specs
    assert storage.received[0]['new_from_source'] is False
    assert len(requested) == 3
    assert len(list(tmp_path.glob('*.html'))) == 3


def test_sync_keeps_incomplete_future_launch_unknown(monkeypatch, tmp_path):
    catalog = official.CATALOGS['apple']
    landing = 'https://www.apple.com.cn/iphone-duo/'
    specs = landing + 'specs/'
    install_transport(monkeypatch, {
        catalog: '<a href="/iphone-duo/">iPhone Duo<span class="badge-new">新款</span></a>',
        landing: '<main>购买 iPhone Duo，10月23日发售</main><a href="/iphone-duo/specs/">技术规格</a>',
        specs: '<title>iPhone Duo - 技术规格</title><div class="techspecs-row"><div class="techspecs-rowheader">芯片</div><div class="techspecs-column">A20 Pro</div></div>',
    })
    report = official.sync_official(brands=['apple'], delay=0, cache_dir=tmp_path)
    raw = report['raws'][0]
    assert raw['availability'] == 'unknown'
    assert raw['specs']['官网发售信息'] == '10月23日发售'
    assert '上市日期' not in raw['specs']


def test_sync_reports_failed_page_and_continues_other_model(monkeypatch, tmp_path):
    catalog = official.CATALOGS['vivo']
    install_transport(monkeypatch, {catalog: '<a href="/vivo/x900/">X900</a><a href="/vivo/x901/">X901</a>'})
    report = official.sync_official(brands=['vivo'], delay=0, cache_dir=tmp_path)
    assert len(report['errors']) == 2
    assert report['raws'] == []
    assert report['coverage']['vivo']['pending'] == 0


def test_unsupported_source_is_explicit():
    with pytest.raises(ValueError, match='不支持'):
        official.sync_official(brands=['unknown'])


def test_spec_link_must_be_for_same_product_even_with_global_navigation():
    soup = BeautifulSoup('''<a href="/vivo/param/x300">导航其它产品参数</a>
        <a href="/vivo/param/x500">本机参数</a>''', 'html.parser')
    assert official._specification_links(soup, 'https://www.vivo.com.cn/vivo/x500/', 'vivo') == [
        'https://www.vivo.com.cn/vivo/param/x500']


def test_explicit_sale_date_uses_china_business_day(monkeypatch, tmp_path):
    catalog = official.CATALOGS['apple']
    landing = 'https://www.apple.com.cn/iphone-duo/'
    install_transport(monkeypatch, {
        catalog: '<a href="/iphone-duo/">iPhone Duo</a>',
        landing: '<main>2026年10月4日发售</main><a href="/iphone-duo/specs/">规格</a>',
        landing + 'specs/': '<title>iPhone Duo</title><div class="techspecs-row"><div class="techspecs-rowheader">芯片</div><div class="techspecs-column">A20 Pro</div></div>',
    })
    monkeypatch.setattr(official, '_utc', lambda: '2026-10-03T23:30:00+00:00')
    monkeypatch.setattr(official, '_today_cn', lambda: '2026-10-04')
    raw = official.sync_official(brands=['apple'], delay=0, cache_dir=tmp_path)['raws'][0]
    assert raw['availability'] == 'listed'
    assert raw['specs']['上市日期'] == '2026-10-04'


def test_sync_can_continue_capped_catalog_without_refetching_first_model(monkeypatch, tmp_path):
    catalog = official.CATALOGS['vivo']
    requested = install_transport(monkeypatch, {
        catalog: '<a href="/vivo/x900/">X900</a><a href="/vivo/x901/">X901</a>',
        'https://www.vivo.com.cn/vivo/x901/': '<a href="/vivo/param/x901">规格</a>',
        'https://www.vivo.com.cn/vivo/param/x901': '<title>vivo X901</title>' + vivo_section('处理器', {'CPU型号': '天玑9600'}),
    })
    report = official.sync_official(brands=['vivo'], delay=0, cache_dir=tmp_path,
                                    max_per_brand=1, offset_per_brand={'vivo': 1})
    assert 'https://www.vivo.com.cn/vivo/x900/' not in requested
    assert report['coverage']['vivo']['pending'] == 0
    assert report['coverage']['vivo']['next_offset'] is None
    assert report['raws'][0]['name'] == 'vivo X901'


def test_series_peer_discovery_retains_actual_parent_page_time(monkeypatch, tmp_path):
    catalog = official.CATALOGS['vivo']
    landing = 'https://www.vivo.com.cn/vivo/x900promax/'
    install_transport(monkeypatch, {
        catalog: '<a href="/vivo/x900promax/">X900 Pro Max</a>',
        landing: '<a href="/vivo/x900/">X900</a><a href="/vivo/param/x900promax">规格</a>',
        'https://www.vivo.com.cn/vivo/param/x900promax': '<title>vivo X900 Pro Max</title>' + vivo_section('CPU', {'CPU型号': 'CPU'}),
        'https://www.vivo.com.cn/vivo/x900/': '<a href="/vivo/param/x900">规格</a>',
        'https://www.vivo.com.cn/vivo/param/x900': '<title>vivo X900</title>' + vivo_section('CPU', {'CPU型号': 'CPU'}),
    })
    report = official.sync_official(brands=['vivo'], delay=0, cache_dir=tmp_path)
    assert report['raws'][1]['new_release_catalog_url'] == landing
    assert report['raws'][1]['catalog_fetched_at'] == TIME


def test_http_200_wrong_body_model_is_reported_not_published(monkeypatch, tmp_path):
    catalog = official.CATALOGS['vivo']
    install_transport(monkeypatch, {
        catalog: '<a href="/vivo/x500/">vivo X500</a>',
        'https://www.vivo.com.cn/vivo/x500/': '<a href="/vivo/param/x500">规格</a>',
        'https://www.vivo.com.cn/vivo/param/x500': '<title>vivo X900</title>' + vivo_section('CPU', {'CPU型号': '天玑9600'}) + vivo_section('上市时间', {'': '2026年9月'}),
    })
    class Storage:
        def import_many(self, raws):
            pytest.fail('错误机型不得入库')
    report = official.sync_official(Storage(), brands=['vivo'], delay=0, cache_dir=tmp_path)
    assert report['raws'] == []
    assert report['imported'] == 0
    assert report['coverage']['vivo']['collected'] == 0
    assert report['coverage']['vivo']['models'][0]['record_ids'] is None
    assert '正文机型与请求不一致' in report['errors'][0]['message']


def test_wrong_variant_name_is_rejected_even_if_title_matches():
    html = '<title>vivo X500 专业影像旗舰</title>' + vivo_section('建议零售价', {
        '': 'vivo X900（12GB+256GB）：5499.00元'
    })
    with pytest.raises(ValueError, match='正文机型与请求不一致'):
        official.parse_specifications(html, 'https://www.vivo.com.cn/vivo/param/x500', 'vivo', fetched_at=TIME)


@pytest.mark.parametrize('requested,title', [('x500', 'vivo X500 Pro'), ('x500pro', 'vivo X500'), ('x500', 'vivo X5000')])
def test_exact_model_identity_rejects_short_prefixes(requested, title):
    html = '<title>' + title + '</title>' + vivo_section('CPU', {'CPU型号': 'CPU'})
    with pytest.raises(ValueError, match='正文机型与请求不一致'):
        official.parse_specifications(html, 'https://www.vivo.com.cn/vivo/param/' + requested, 'vivo', fetched_at=TIME)


def test_huawei_ultimate_design_chinese_alias_is_same_explicit_model():
    html = '''<h1>HUAWEI Mate 90 RS 非凡大师 规格参数</h1><li class="large-accordion__item">
    <span class="large-accordion__title">处理器</span><div class="large-accordion__inner"><p>麒麟9030</p></div></li>'''
    raw = official.parse_specifications(html, 'https://consumer.huawei.com/cn/phones/mate90-rs-ultimate-design/specs/', 'huawei', fetched_at=TIME)[0]
    assert raw['name'] == '华为 Mate 90 RS 非凡大师'


def test_apple_max_requires_explicit_same_page_pro_and_max_columns():
    html = '''<title>iPhone 18 Pro - 技术规格</title><div class="techspecs-columnheader">iPhone 18 Pro Max</div>
    <div class="techspecs-row"><div class="techspecs-rowheader">芯片</div><div class="techspecs-column">A20 Pro</div></div>'''
    with pytest.raises(ValueError, match='正文机型与请求不一致'):
        official.parse_specifications(html, 'https://www.apple.com.cn/iphone-18-pro/specs/', 'apple', fetched_at=TIME)


@pytest.mark.parametrize('name', ['iQOO 16', 'iQOO16'])
def test_iqoo_keeps_brand_and_same_family_as_zol_without_changing_id(name):
    from phone_assistant.cleaning import clean_phone
    payload = [{"name": 1, "code": 2, "seoTitle": 3}, name, 'iqoo16', name]
    html = '<title>' + name + '</title><script type="application/json">' + json.dumps(payload) + '</script>' + vivo_section('CPU', {'CPU型号': '骁龙'})
    raw = official.parse_specifications(html, 'https://www.vivo.com.cn/vivo/param/iqoo16', 'vivo', fetched_at=TIME)[0]
    zol = {'id': '1', 'name': 'iQOO 16(12GB/256GB)', 'brand': 'iQOO', 'fetched_at': TIME, 'origin': 'zol', 'specs': {}}
    assert raw['brand'] == 'iQOO'
    assert raw['platform'] == 'vivo'
    assert raw['id'] == 'official:vivo:vivo:param:iqoo16'
    assert clean_phone(raw)['family_key'] == clean_phone(zol)['family_key']


def test_vivo_primary_ssr_name_handles_marketing_title_without_prefix_match():
    payload = [{"name": 1, "code": 2, "seoTitle": 3}, 'S60 元气版', 's60e', 'vivo S60 元气版 4K原生感Live']
    html = '<title>vivo S60 元气版 4K原生感Live</title><script type="application/json">' + json.dumps(payload) + '</script>' + vivo_section('CPU', {'CPU型号': 'CPU'})
    raw = official.parse_specifications(html, 'https://www.vivo.com.cn/vivo/param/s60e', 'vivo', fetched_at=TIME)[0]
    assert raw['name'] == 'vivo S60 元气版'
    with pytest.raises(ValueError, match='正文机型与请求不一致'):
        official.parse_specifications(html, 'https://www.vivo.com.cn/vivo/param/s60', 'vivo', fetched_at=TIME)
