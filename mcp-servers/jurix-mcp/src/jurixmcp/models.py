from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class AccountStatus(StrEnum):
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    EXPIRED = "expired"
    BANNED = "banned"
    EXHAUSTED = "exhausted"
    INVALID = "invalid"


@dataclass(slots=True)
class AccountRecord:
    id: int
    email: str
    password: str
    created_at: datetime
    trial_expires_at: datetime
    status: AccountStatus
    fail_count: int
    last_used_at: datetime | None
    last_checked_at: datetime | None


@dataclass(slots=True)
class SessionRecord:
    id: int
    account_id: int
    csrf_token: str | None
    cookies: dict[str, str]
    user_agent: str
    is_valid: bool
    updated_at: datetime


@dataclass(slots=True)
class AuthSession:
    account: AccountRecord
    csrf_token: str | None
    cookies: dict[str, str]
    user_agent: str


@dataclass(slots=True)
class SearchResult:
    id: str | None
    title: str
    link: str
    author: str | None = None
    journal: str | None = None
    issue_date: str | None = None
    metadata_raw: str | None = None
    snippet: str | None = None


@dataclass(slots=True)
class DownloadResult:
    source: str
    article_id: str
    article_url: str
    title: str
    author: str
    journal_name: str | None
    editor: str | None
    issn: str | None
    volume: int | None
    issue: int | None
    issue_label: str | None
    published_start_page: int | None
    published_end_page: int | None
    download_start_page: int
    download_end_page: int
    downloaded_page_count: int
    download_duration_ms: int
    download_dir: str
    pdf_filename: str
    pdf_size_bytes: int
    pdf_sha256: str
    start_page: int
    end_page: int
    slug: str
    page_count: int
    pdf_path: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "article_id": self.article_id,
            "article_url": self.article_url,
            "title": self.title,
            "author": self.author,
            "journal_name": self.journal_name,
            "editor": self.editor,
            "issn": self.issn,
            "volume": self.volume,
            "issue": self.issue,
            "issue_label": self.issue_label,
            "published_start_page": self.published_start_page,
            "published_end_page": self.published_end_page,
            "download_start_page": self.download_start_page,
            "download_end_page": self.download_end_page,
            "downloaded_page_count": self.downloaded_page_count,
            "download_duration_ms": self.download_duration_ms,
            "download_dir": self.download_dir,
            "pdf_filename": self.pdf_filename,
            "pdf_size_bytes": self.pdf_size_bytes,
            "pdf_sha256": self.pdf_sha256,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "slug": self.slug,
            "page_count": self.page_count,
            "pdf_path": self.pdf_path,
        }
