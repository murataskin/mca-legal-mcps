from jurixmcp.jurix_http import JurixHttpClient


class DummySession:
    pass


def test_resolve_page_range_corrects_off_by_one_start(monkeypatch):
    client = JurixHttpClient("https://www.jurix.com.tr", "ua")

    def fake_exists(_session, page_num, _slug):
        return 83 <= page_num <= 98

    monkeypatch.setattr(client, "_image_exists", fake_exists)
    start, end = client._resolve_page_range(DummySession(), "slug", 84, 98)

    assert start == 83
    assert end == 98


def test_resolve_page_range_corrects_end_if_hint_too_high(monkeypatch):
    client = JurixHttpClient("https://www.jurix.com.tr", "ua")

    def fake_exists(_session, page_num, _slug):
        return 83 <= page_num <= 98

    monkeypatch.setattr(client, "_image_exists", fake_exists)
    start, end = client._resolve_page_range(DummySession(), "slug", 83, 101)

    assert start == 83
    assert end == 98
