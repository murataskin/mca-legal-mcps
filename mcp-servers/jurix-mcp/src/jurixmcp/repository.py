from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import AccountRecord, AccountStatus, DownloadResult, SessionRecord


ISO = "%Y-%m-%dT%H:%M:%S.%f%z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def dt_to_str(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime(ISO)


def str_to_dt(value: str) -> datetime:
    return datetime.strptime(value, ISO)


class AccountRepository:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    trial_expires_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    fail_count INTEGER NOT NULL DEFAULT 0,
                    last_used_at TEXT,
                    last_checked_at TEXT
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL UNIQUE,
                    csrf_token TEXT,
                    cookies_json TEXT NOT NULL,
                    user_agent TEXT NOT NULL,
                    is_valid INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(account_id) REFERENCES accounts(id)
                );

                CREATE TABLE IF NOT EXISTS account_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER,
                    event_type TEXT NOT NULL,
                    detail_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(account_id) REFERENCES accounts(id)
                );

                CREATE INDEX IF NOT EXISTS idx_accounts_status_expires
                    ON accounts(status, trial_expires_at);

                CREATE TABLE IF NOT EXISTS article_downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    article_id TEXT NOT NULL,
                    article_url TEXT,
                    slug TEXT,
                    title TEXT,
                    author TEXT,
                    journal_name TEXT,
                    editor TEXT,
                    issn TEXT,
                    volume INTEGER,
                    issue INTEGER,
                    issue_label TEXT,
                    published_start_page INTEGER,
                    published_end_page INTEGER,
                    download_start_page INTEGER,
                    download_end_page INTEGER,
                    downloaded_page_count INTEGER NOT NULL DEFAULT 0,
                    download_duration_ms INTEGER,
                    download_dir TEXT,
                    pdf_filename TEXT,
                    pdf_path TEXT,
                    pdf_size_bytes INTEGER,
                    pdf_sha256 TEXT,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    error_message TEXT,
                    first_downloaded_at TEXT NOT NULL,
                    last_downloaded_at TEXT NOT NULL,
                    last_verified_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source, article_id)
                );

                CREATE INDEX IF NOT EXISTS idx_article_downloads_status
                    ON article_downloads(status);
                """
            )

    def upsert_account(
        self,
        email: str,
        password: str,
        created_at: datetime,
        trial_expires_at: datetime,
        status: AccountStatus = AccountStatus.ACTIVE,
    ) -> AccountRecord:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO accounts(email, password, created_at, trial_expires_at, status)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    password=excluded.password,
                    trial_expires_at=excluded.trial_expires_at,
                    status=excluded.status
                """,
                (email, password, dt_to_str(created_at), dt_to_str(trial_expires_at), status.value),
            )
        record = self.get_account_by_email(email)
        if record is None:
            raise RuntimeError("Account upsert failed")
        return record

    def get_account_by_email(self, email: str) -> AccountRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE email = ?", (email,)).fetchone()
        return self._row_to_account(row) if row else None

    def acquire_best_account(self, expiry_buffer_hours: int, exclude_email: str | None = None) -> AccountRecord | None:
        cutoff = dt_to_str(utcnow() + timedelta(hours=expiry_buffer_hours))
        params: list[str] = [AccountStatus.ACTIVE.value, cutoff]
        exclude_clause = ""
        if exclude_email:
            exclude_clause = "AND email != ?"
            params.append(exclude_email)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM accounts
                WHERE status = ?
                  AND trial_expires_at > ?
                  {exclude_clause}
                ORDER BY last_used_at IS NOT NULL, last_used_at ASC, created_at ASC
                LIMIT 1
                """.format(exclude_clause=exclude_clause),
                tuple(params),
            ).fetchone()
        return self._row_to_account(row) if row else None

    def count_ready_accounts(self, expiry_buffer_hours: int) -> int:
        cutoff = dt_to_str(utcnow() + timedelta(hours=expiry_buffer_hours))
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c FROM accounts
                WHERE status = ? AND trial_expires_at > ?
                """,
                (AccountStatus.ACTIVE.value, cutoff),
            ).fetchone()
        return int(row["c"])

    def count_accounts_by_status(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS c
                FROM accounts
                GROUP BY status
                """
            ).fetchall()
        return {str(row["status"]): int(row["c"]) for row in rows}

    def mark_status(self, email: str, status: AccountStatus) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE accounts SET status = ?, last_checked_at = ? WHERE email = ?", (status.value, dt_to_str(utcnow()), email))

    def touch_account(self, email: str) -> None:
        now = dt_to_str(utcnow())
        with self._connect() as conn:
            conn.execute("UPDATE accounts SET last_used_at = ?, last_checked_at = ? WHERE email = ?", (now, now, email))

    def increment_fail_count(self, email: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE accounts SET fail_count = fail_count + 1, last_checked_at = ? WHERE email = ?", (dt_to_str(utcnow()), email))

    def save_session(
        self,
        account_id: int,
        csrf_token: str | None,
        cookies: dict[str, str],
        user_agent: str,
        is_valid: bool,
    ) -> SessionRecord:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions(account_id, csrf_token, cookies_json, user_agent, is_valid, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    csrf_token=excluded.csrf_token,
                    cookies_json=excluded.cookies_json,
                    user_agent=excluded.user_agent,
                    is_valid=excluded.is_valid,
                    updated_at=excluded.updated_at
                """,
                (
                    account_id,
                    csrf_token,
                    json.dumps(cookies, ensure_ascii=True),
                    user_agent,
                    1 if is_valid else 0,
                    dt_to_str(utcnow()),
                ),
            )
            row = conn.execute("SELECT * FROM sessions WHERE account_id = ?", (account_id,)).fetchone()
        if row is None:
            raise RuntimeError("Session save failed")
        return self._row_to_session(row)

    def get_session_by_account_id(self, account_id: int) -> SessionRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE account_id = ?", (account_id,)).fetchone()
        return self._row_to_session(row) if row else None

    def add_event(self, account_id: int | None, event_type: str, detail: dict | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO account_events(account_id, event_type, detail_json, created_at) VALUES (?, ?, ?, ?)",
                (account_id, event_type, json.dumps(detail or {}, ensure_ascii=True), dt_to_str(utcnow())),
            )

    def upsert_download_success(self, result: DownloadResult) -> None:
        now = dt_to_str(utcnow())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO article_downloads(
                    source, article_id, article_url, slug, title, author, journal_name, editor, issn,
                    volume, issue, issue_label, published_start_page, published_end_page,
                    download_start_page, download_end_page, downloaded_page_count, download_duration_ms,
                    download_dir, pdf_filename, pdf_path, pdf_size_bytes, pdf_sha256,
                    status, attempt_count, error_message,
                    first_downloaded_at, last_downloaded_at, last_verified_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NULL, ?, ?, ?, ?, ?)
                ON CONFLICT(source, article_id) DO UPDATE SET
                    article_url=excluded.article_url,
                    slug=excluded.slug,
                    title=excluded.title,
                    author=excluded.author,
                    journal_name=excluded.journal_name,
                    editor=excluded.editor,
                    issn=excluded.issn,
                    volume=excluded.volume,
                    issue=excluded.issue,
                    issue_label=excluded.issue_label,
                    published_start_page=excluded.published_start_page,
                    published_end_page=excluded.published_end_page,
                    download_start_page=excluded.download_start_page,
                    download_end_page=excluded.download_end_page,
                    downloaded_page_count=excluded.downloaded_page_count,
                    download_duration_ms=excluded.download_duration_ms,
                    download_dir=excluded.download_dir,
                    pdf_filename=excluded.pdf_filename,
                    pdf_path=excluded.pdf_path,
                    pdf_size_bytes=excluded.pdf_size_bytes,
                    pdf_sha256=excluded.pdf_sha256,
                    status='downloaded',
                    error_message=NULL,
                    attempt_count=article_downloads.attempt_count + 1,
                    last_downloaded_at=excluded.last_downloaded_at,
                    last_verified_at=excluded.last_verified_at,
                    updated_at=excluded.updated_at
                """,
                (
                    result.source,
                    result.article_id,
                    result.article_url,
                    result.slug,
                    result.title,
                    result.author,
                    result.journal_name,
                    result.editor,
                    result.issn,
                    result.volume,
                    result.issue,
                    result.issue_label,
                    result.published_start_page,
                    result.published_end_page,
                    result.download_start_page,
                    result.download_end_page,
                    result.downloaded_page_count,
                    result.download_duration_ms,
                    result.download_dir,
                    result.pdf_filename,
                    result.pdf_path,
                    result.pdf_size_bytes,
                    result.pdf_sha256,
                    "downloaded",
                    now,
                    now,
                    now,
                    now,
                    now,
                ),
            )

    def upsert_download_failure(self, source: str, article_id: str, error_message: str) -> None:
        now = dt_to_str(utcnow())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO article_downloads(
                    source, article_id, status, attempt_count, error_message,
                    first_downloaded_at, last_downloaded_at, created_at, updated_at
                )
                VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
                ON CONFLICT(source, article_id) DO UPDATE SET
                    status='failed',
                    error_message=excluded.error_message,
                    attempt_count=article_downloads.attempt_count + 1,
                    last_downloaded_at=excluded.last_downloaded_at,
                    updated_at=excluded.updated_at
                """,
                (source, article_id, "failed", error_message, now, now, now, now),
            )

    def get_download_by_article(self, source: str, article_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM article_downloads WHERE source = ? AND article_id = ?",
                (source, article_id),
            ).fetchone()

    def _row_to_account(self, row: sqlite3.Row) -> AccountRecord:
        return AccountRecord(
            id=int(row["id"]),
            email=str(row["email"]),
            password=str(row["password"]),
            created_at=str_to_dt(str(row["created_at"])),
            trial_expires_at=str_to_dt(str(row["trial_expires_at"])),
            status=AccountStatus(str(row["status"])),
            fail_count=int(row["fail_count"]),
            last_used_at=str_to_dt(str(row["last_used_at"])) if row["last_used_at"] else None,
            last_checked_at=str_to_dt(str(row["last_checked_at"])) if row["last_checked_at"] else None,
        )

    def _row_to_session(self, row: sqlite3.Row) -> SessionRecord:
        return SessionRecord(
            id=int(row["id"]),
            account_id=int(row["account_id"]),
            csrf_token=str(row["csrf_token"]) if row["csrf_token"] else None,
            cookies=json.loads(str(row["cookies_json"])),
            user_agent=str(row["user_agent"]),
            is_valid=bool(row["is_valid"]),
            updated_at=str_to_dt(str(row["updated_at"])),
        )
