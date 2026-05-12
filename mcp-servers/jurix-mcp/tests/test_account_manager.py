from datetime import timedelta

from jurixmcp.account_manager import AccountManager
from jurixmcp.config import Settings
from jurixmcp.models import AccountStatus, AuthSession
from jurixmcp.repository import AccountRepository, utcnow


class FakeCookies:
    def __init__(self, data=None):
        self._data = data or {"laravel_session": "seed"}

    def get_dict(self):
        return dict(self._data)


class FakeSession:
    def __init__(self, user_agent="ua", cookies=None):
        self.headers = {"User-Agent": user_agent}
        self.cookies = FakeCookies(cookies)


class FakeJurixClient:
    def __init__(self, should_validate=True):
        self.should_validate = should_validate
        self.login_called = 0

    def new_session(self, user_agent=None, cookies=None):
        return FakeSession(user_agent or "ua", cookies)

    def validate_session(self, session):
        return self.should_validate

    def bootstrap_csrf(self, session):
        return "csrf0"

    def login(self, session, email, password, csrf):
        self.login_called += 1
        return "csrf1"


class FakeMailProvider:
    def create_account(self):
        raise AssertionError("create_account should not be called in this test")


def build_manager(tmp_path, fake_client):
    settings = Settings(
        database_path=tmp_path / "test.db",
        download_root=tmp_path / "downloads",
        account_pool_target=1,
        account_expiry_buffer_hours=24,
    )
    repo = AccountRepository(settings.database_path)
    manager = AccountManager(settings, repo, fake_client, FakeMailProvider())
    now = utcnow()
    account = repo.upsert_account(
        email="demo@example.com",
        password="pw",
        created_at=now,
        trial_expires_at=now + timedelta(days=5),
        status=AccountStatus.ACTIVE,
    )
    repo.save_session(account.id, "csrf-old", {"laravel_session": "abc"}, "ua", True)
    return manager, repo


def test_get_valid_auth_session_reuses_valid_session(tmp_path):
    fake_client = FakeJurixClient(should_validate=True)
    manager, _ = build_manager(tmp_path, fake_client)

    auth = manager.get_valid_auth_session()

    assert auth.account.email == "demo@example.com"
    assert auth.csrf_token == "csrf-old"
    assert fake_client.login_called == 0


def test_get_valid_auth_session_refreshes_invalid_session(tmp_path):
    fake_client = FakeJurixClient(should_validate=False)
    manager, repo = build_manager(tmp_path, fake_client)

    auth = manager.get_valid_auth_session()

    assert auth.csrf_token == "csrf1"
    assert fake_client.login_called == 1
    account = repo.get_account_by_email("demo@example.com")
    assert account is not None
    saved = repo.get_session_by_account_id(account.id)
    assert saved is not None
    assert saved.csrf_token == "csrf1"


def test_rotate_auth_session_switches_to_another_ready_account(tmp_path):
    fake_client = FakeJurixClient(should_validate=True)
    settings = Settings(
        database_path=tmp_path / "test.db",
        download_root=tmp_path / "downloads",
        account_pool_target=1,
        account_expiry_buffer_hours=24,
    )
    repo = AccountRepository(settings.database_path)
    manager = AccountManager(settings, repo, fake_client, FakeMailProvider())
    now = utcnow()
    first = repo.upsert_account(
        email="first@example.com",
        password="pw1",
        created_at=now,
        trial_expires_at=now + timedelta(days=5),
        status=AccountStatus.ACTIVE,
    )
    second = repo.upsert_account(
        email="second@example.com",
        password="pw2",
        created_at=now + timedelta(seconds=1),
        trial_expires_at=now + timedelta(days=5),
        status=AccountStatus.ACTIVE,
    )
    repo.save_session(first.id, "csrf-first", {"laravel_session": "a"}, "ua", True)
    repo.save_session(second.id, "csrf-second", {"laravel_session": "b"}, "ua", True)

    auth = manager.rotate_auth_session()

    assert auth.account.email == "second@example.com"
    assert auth.csrf_token == "csrf-second"
    assert fake_client.login_called == 0


def test_rotate_auth_session_creates_new_account_when_no_alternative_exists(tmp_path):
    fake_client = FakeJurixClient(should_validate=True)
    settings = Settings(
        database_path=tmp_path / "test.db",
        download_root=tmp_path / "downloads",
        account_pool_target=1,
        account_expiry_buffer_hours=24,
    )
    repo = AccountRepository(settings.database_path)
    now = utcnow()
    existing = repo.upsert_account(
        email="only@example.com",
        password="pw",
        created_at=now,
        trial_expires_at=now + timedelta(days=5),
        status=AccountStatus.ACTIVE,
    )
    repo.save_session(existing.id, "csrf-only", {"laravel_session": "a"}, "ua", True)

    class CreatingManager(AccountManager):
        def create_account_and_session(self) -> AuthSession:
            created_now = utcnow()
            created = self.repository.upsert_account(
                email="new@example.com",
                password="pw-new",
                created_at=created_now,
                trial_expires_at=created_now + timedelta(days=5),
                status=AccountStatus.ACTIVE,
            )
            self.repository.save_session(created.id, "csrf-new", {"laravel_session": "new"}, "ua", True)
            return AuthSession(
                account=created,
                csrf_token="csrf-new",
                cookies={"laravel_session": "new"},
                user_agent="ua",
            )

    manager = CreatingManager(settings, repo, fake_client, FakeMailProvider())

    auth = manager.rotate_auth_session()

    assert auth.account.email == "new@example.com"
    assert auth.csrf_token == "csrf-new"
