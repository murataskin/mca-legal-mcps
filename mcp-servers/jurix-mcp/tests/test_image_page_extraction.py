from jurixmcp.jurix_http import JurixHttpClient


def test_extract_image_pages_from_html_parses_min_max_range():
    slug = "886ca7c645d24a01b446b94e95cfa6b7"
    html = """
    <img src="/getpageimage/88/886ca7c645d24a01b446b94e95cfa6b7?ts=1">
    <img src="/getpageimage/89/886ca7c645d24a01b446b94e95cfa6b7?ts=1">
    <img src="/getpageimage/103/886ca7c645d24a01b446b94e95cfa6b7?ts=1">
    """
    pages = JurixHttpClient._extract_image_pages_from_html(html, slug)
    assert pages == [88, 89, 103]
