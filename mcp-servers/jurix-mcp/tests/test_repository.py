from datetime import timedelta

from jurixmcp.models import AccountStatus, DownloadResult
from jurixmcp.repository import AccountRepository, utcnow


def test_repository_upsert_and_session_roundtrip(tmp_path):
    repo = AccountRepository(tmp_path / "test.db")
    now = utcnow()

    account = repo.upsert_account(
        email="a@example.com",
        password="secret",
        created_at=now,
        trial_expires_at=now + timedelta(days=7),
        status=AccountStatus.ACTIVE,
    )

    saved_session = repo.save_session(
        account_id=account.id,
        csrf_token="csrf123",
        cookies={"laravel_session": "abc"},
        user_agent="ua",
        is_valid=True,
    )

    loaded = repo.get_session_by_account_id(account.id)
    assert loaded is not None
    assert loaded.id == saved_session.id
    assert loaded.cookies["laravel_session"] == "abc"


def test_repository_count_ready_respects_expiry_buffer(tmp_path):
    repo = AccountRepository(tmp_path / "test.db")
    now = utcnow()

    repo.upsert_account(
        email="ready@example.com",
        password="x",
        created_at=now,
        trial_expires_at=now + timedelta(days=3),
        status=AccountStatus.ACTIVE,
    )
    repo.upsert_account(
        email="near_expiry@example.com",
        password="x",
        created_at=now,
        trial_expires_at=now + timedelta(hours=2),
        status=AccountStatus.ACTIVE,
    )

    assert repo.count_ready_accounts(expiry_buffer_hours=24) == 1


def test_repository_counts_accounts_by_status(tmp_path):
    repo = AccountRepository(tmp_path / "test.db")
    now = utcnow()

    repo.upsert_account(
        email="active@example.com",
        password="x",
        created_at=now,
        trial_expires_at=now + timedelta(days=3),
        status=AccountStatus.ACTIVE,
    )
    repo.upsert_account(
        email="invalid@example.com",
        password="x",
        created_at=now,
        trial_expires_at=now + timedelta(days=3),
        status=AccountStatus.INVALID,
    )

    counts = repo.count_accounts_by_status()

    assert counts["active"] == 1
    assert counts["invalid"] == 1


def test_repository_acquire_best_account_can_exclude_email(tmp_path):
    repo = AccountRepository(tmp_path / "test.db")
    now = utcnow()

    first = repo.upsert_account(
        email="first@example.com",
        password="x",
        created_at=now,
        trial_expires_at=now + timedelta(days=3),
        status=AccountStatus.ACTIVE,
    )
    second = repo.upsert_account(
        email="second@example.com",
        password="x",
        created_at=now + timedelta(seconds=1),
        trial_expires_at=now + timedelta(days=3),
        status=AccountStatus.ACTIVE,
    )

    selected = repo.acquire_best_account(expiry_buffer_hours=24)
    excluded = repo.acquire_best_account(expiry_buffer_hours=24, exclude_email=first.email)

    assert selected is not None
    assert excluded is not None
    assert selected.email == "first@example.com"
    assert excluded.email == second.email


def test_repository_tracks_download_success_and_failure(tmp_path):
    repo = AccountRepository(tmp_path / "test.db")

    result = DownloadResult(
        source="jurix",
        article_id="11544",
        article_url="https://www.jurix.com.tr/article/11544",
        title="Kira Tespit Davası ve Esasları",
        author="Gizem KILIÇ ÖZTÜRK",
        journal_name="Türkiye Barolar Birliği Dergisi",
        editor="Özlem BİLGİLİOĞLU",
        issn="1304-2408",
        volume=29,
        issue=129,
        issue_label="Mart 2017",
        published_start_page=229,
        published_end_page=260,
        download_start_page=230,
        download_end_page=261,
        downloaded_page_count=32,
        download_duration_ms=1500,
        download_dir="downloads/Kira_Tespit_Davasi_ve_Esaslari",
        pdf_filename="Kira_Tespit_Davasi_ve_Esaslari.pdf",
        pdf_size_bytes=123456,
        pdf_sha256="a" * 64,
        start_page=230,
        end_page=261,
        slug="d447b6359f23c957e2a393b32c71aabb",
        page_count=32,
        pdf_path="downloads/Kira_Tespit_Davasi_ve_Esaslari/Kira_Tespit_Davasi_ve_Esaslari.pdf",
    )
    repo.upsert_download_success(result)

    row = repo.get_download_by_article("jurix", "11544")
    assert row is not None
    assert row["status"] == "downloaded"
    assert row["journal_name"] == "Türkiye Barolar Birliği Dergisi"
    assert row["published_start_page"] == 229
    assert row["download_start_page"] == 230

    repo.upsert_download_failure("jurix", "11544", "network timeout")
    row2 = repo.get_download_by_article("jurix", "11544")
    assert row2 is not None
    assert row2["status"] == "failed"
    assert row2["error_message"] == "network timeout"
