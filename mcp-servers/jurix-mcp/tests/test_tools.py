from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from jurixmcp.errors import DownloadError
from jurixmcp.models import AccountStatus, AuthSession, SearchResult
from jurixmcp.repository import utcnow
from jurixmcp.tools import JurixToolService


class FakeCookies:
    def __init__(self, data=None):
        self._data = data or {"laravel_session": "seed"}

    def get_dict(self):
        return dict(self._data)


class FakeSession:
    def __init__(self, user_agent="ua", cookies=None):
        self.headers = {"User-Agent": user_agent}
        self.cookies = FakeCookies(cookies)


@dataclass
class FakeAccount:
    id: int = 1
    email: str = "demo@example.com"
    password: str = "pw"
    trial_expires_at: datetime = field(default_factory=lambda: utcnow() + timedelta(days=5))
    status: AccountStatus = AccountStatus.ACTIVE
    fail_count: int = 0
    last_used_at: datetime | None = None
    last_checked_at: datetime | None = None


@dataclass
class FakeSessionRecord:
    is_valid: bool = True
    updated_at: datetime = field(default_factory=utcnow)


class FakeResult:
    def as_dict(self):
        return {"ok": True}


class FakeSettings:
    def __init__(self, download_root, default_user_agent="ua-default", account_pool_target=3, account_expiry_buffer_hours=24):
        self.download_root = download_root
        self.default_user_agent = default_user_agent
        self.account_pool_target = account_pool_target
        self.account_expiry_buffer_hours = account_expiry_buffer_hours


class FakeAccountManager:
    def __init__(self, tmp_path, repo, ready_after_ensure=None):
        self.settings = FakeSettings(tmp_path / "downloads")
        self.repository = repo
        self.auth = AuthSession(
            account=FakeAccount(),
            csrf_token="csrf-old",
            cookies={"laravel_session": "stale"},
            user_agent="ua-auth",
        )
        self.ensure_calls = 0
        self.ready_after_ensure = ready_after_ensure or self.settings.account_pool_target
        self.rotated_auth = AuthSession(
            account=FakeAccount(id=2, email="rotated@example.com"),
            csrf_token="csrf-rotated",
            cookies={"laravel_session": "rotated"},
            user_agent="ua-rotated",
        )

    def get_valid_auth_session(self):
        return self.auth

    def rotate_auth_session(self):
        return self.rotated_auth

    def ensure_pool_size(self):
        self.ensure_calls += 1
        self.repository.ready_accounts = self.ready_after_ensure
        self.repository.account_counts["active"] = max(
            self.repository.account_counts.get("active", 0),
            self.ready_after_ensure,
        )


class FakeRepository:
    def __init__(self, ready_accounts=1, account_counts=None, selected_account=None, session_record=None):
        self.failures = []
        self.successes = []
        self.saved_sessions = []
        self.ready_accounts = ready_accounts
        self.account_counts = account_counts or {"active": ready_accounts}
        self.selected_account = selected_account or FakeAccount()
        self.session_record = session_record or FakeSessionRecord()

    def upsert_download_failure(self, source, article_id, error_message):
        self.failures.append((source, article_id, error_message))

    def upsert_download_success(self, result):
        self.successes.append(result)

    def save_session(self, account_id, csrf_token, cookies, user_agent, is_valid):
        self.saved_sessions.append((account_id, csrf_token, cookies, user_agent, is_valid))

    def count_ready_accounts(self, expiry_buffer_hours):
        return self.ready_accounts

    def count_accounts_by_status(self):
        return dict(self.account_counts)

    def acquire_best_account(self, expiry_buffer_hours, exclude_email=None):
        if exclude_email and self.selected_account.email == exclude_email:
            return None
        return self.selected_account

    def get_account_by_email(self, email: str):
        if email == self.selected_account.email:
            return self.selected_account
        return None

    def get_session_by_account_id(self, account_id: int):
        if account_id == self.selected_account.id:
            return self.session_record
        return None


class FakeJurixClient:
    def __init__(self, search_results=None):
        self.download_calls = 0
        self.bootstrap_calls = 0
        self.login_calls = 0
        self.search_queries = []
        self.search_results = search_results or []

    def new_session(self, user_agent=None, cookies=None):
        return FakeSession(user_agent or "ua", cookies)

    def search(self, session, query, limit):
        self.search_queries.append((query, limit))
        items = list(self.search_results)
        if limit is None:
            return items
        return items[:limit]

    def download_article_pdf(self, session, article_id, output_root):
        self.download_calls += 1
        if self.download_calls == 1:
            raise DownloadError("Unable to extract image slug from article page")
        return FakeResult()

    def bootstrap_csrf(self, session):
        self.bootstrap_calls += 1
        return "csrf-new"

    def login(self, session, email, password, csrf):
        self.login_calls += 1
        return "csrf-logged-in"


def test_jurix_download_pdf_retries_with_fresh_login_on_slug_error(tmp_path):
    repo = FakeRepository()
    account_manager = FakeAccountManager(tmp_path, repo)
    client = FakeJurixClient()
    service = JurixToolService(account_manager, client, repo)

    result = service.jurix_download_pdf("11544")

    assert result == {"ok": True}
    assert client.download_calls == 2
    assert client.bootstrap_calls == 1
    assert client.login_calls == 1
    assert len(repo.saved_sessions) == 1
    assert repo.failures == []
    assert len(repo.successes) == 1


def test_jurix_download_pdf_does_not_retry_other_download_errors(tmp_path):
    repo = FakeRepository()
    account_manager = FakeAccountManager(tmp_path, repo)

    class FailingClient(FakeJurixClient):
        def download_article_pdf(self, session, article_id, output_root):
            raise DownloadError("No pages downloaded")

    service = JurixToolService(account_manager, FailingClient(), repo)

    with pytest.raises(DownloadError, match="No pages downloaded"):
        service.jurix_download_pdf("11544")
    assert len(repo.failures) == 1


def test_jurix_search_rewrites_long_natural_language_queries(tmp_path):
    repo = FakeRepository(ready_accounts=2, account_counts={"active": 2})
    account_manager = FakeAccountManager(tmp_path, repo)
    client = FakeJurixClient(
        search_results=[
            SearchResult(
                id="11544",
                title="Anonim Şirketlerde Huzur Hakkı",
                link="https://www.jurix.com.tr/article/11544",
                author="Yazar",
            )
        ]
    )
    service = JurixToolService(account_manager, client, repo)

    payload = service.jurix_search(
        "Please find Jurix articles about anonim şirket huzur hakkı ve yönetim kurulu üyelerinin mali hakları konusunda bir çalışma",
        limit=3,
    )

    assert payload["status"] == "ok"
    assert payload["search_type"] == "title_keyword_search"
    assert payload["query"]["rewritten"] is True
    assert client.search_queries == [("anonim şirket huzur hakkı yönetim kurulu", 3)]
    assert payload["result_count"] == 1
    assert payload["pool_status"]["healthy"] is False
    assert payload["next_actions"] == [
        "jurix_search succeeded, but the account pool is below target. Call jurix_ensure_pool before heavier use.",
    ]


def test_jurix_search_empty_results_include_pool_recovery_guidance(tmp_path):
    repo = FakeRepository(ready_accounts=0, account_counts={"active": 0, "invalid": 1})
    account_manager = FakeAccountManager(tmp_path, repo)
    client = FakeJurixClient(search_results=[])
    service = JurixToolService(account_manager, client, repo)

    payload = service.jurix_search("kira tespit", limit=5)

    assert payload["status"] == "no_results"
    assert payload["result_count"] == 0
    assert payload["pool_status"]["healthy"] is False
    assert "Call jurix_pool_status if Jurix returned an empty page or no results unexpectedly." in payload["next_actions"]
    assert "If the pool is unhealthy or Jurix still responds empty, call jurix_ensure_pool and rerun jurix_search." in payload["next_actions"]


def test_jurix_ensure_pool_reports_before_and_after_counts(tmp_path):
    repo = FakeRepository(ready_accounts=0, account_counts={"active": 0})
    account_manager = FakeAccountManager(tmp_path, repo, ready_after_ensure=3)
    service = JurixToolService(account_manager, FakeJurixClient(), repo)

    payload = service.jurix_ensure_pool()

    assert account_manager.ensure_calls == 1
    assert payload["ready_accounts_before"] == 0
    assert payload["ready_accounts_after"] == 3
    assert payload["healthy"] is True


def test_jurix_account_status_reports_selected_account(tmp_path):
    repo = FakeRepository(ready_accounts=1, account_counts={"active": 1})
    account_manager = FakeAccountManager(tmp_path, repo)
    service = JurixToolService(account_manager, FakeJurixClient(), repo)

    payload = service.jurix_account_status()

    assert payload["status"] == "ok"
    assert payload["selected_by"] == "best_ready_account"
    assert payload["account"]["email"] == "demo@example.com"
    assert payload["account"]["download_ready"] is True
    assert payload["session"]["present"] is True


def test_jurix_rotate_account_reports_new_account(tmp_path):
    repo = FakeRepository(ready_accounts=2, account_counts={"active": 2})
    account_manager = FakeAccountManager(tmp_path, repo)
    service = JurixToolService(account_manager, FakeJurixClient(), repo)

    payload = service.jurix_rotate_account()

    assert payload["status"] == "ok"
    assert payload["rotated"] is True
    assert payload["previous_account_email"] == "demo@example.com"
    assert payload["current_account"]["email"] == "rotated@example.com"
