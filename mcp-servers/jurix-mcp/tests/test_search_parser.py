from jurixmcp.jurix_http import JurixHttpClient


SAMPLE_HTML = """
<ul class="result">
  <li>
    <h3 class="resultArticleTitle"><a href="/article/12345?x=1">Sample Title</a></h3>
    <ul class="summary">Jane Doe | Journal X | 2025</ul>
    <div><p class="resultSummary">Snippet text</p></div>
  </li>
</ul>
"""


def test_parse_search_results_extracts_expected_fields():
    results = JurixHttpClient.parse_search_results(SAMPLE_HTML, "https://www.jurix.com.tr", limit=None)
    assert len(results) == 1
    item = results[0]
    assert item.id == "12345"
    assert item.title == "Sample Title"
    assert item.link == "https://www.jurix.com.tr/article/12345?x=1"
    assert item.author == "Jane Doe"
    assert item.journal == "Journal X"
    assert item.issue_date == "2025"
    assert item.snippet == "Snippet text"


def test_parse_search_results_honors_limit():
    html = SAMPLE_HTML + SAMPLE_HTML.replace("12345", "99999")
    results = JurixHttpClient.parse_search_results(html, "https://www.jurix.com.tr", limit=1)
    assert len(results) == 1
