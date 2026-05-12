from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
import re
from typing import Any

from .account_manager import AccountManager
from .errors import AccountPoolError, AuthenticationError, DownloadError
from .jurix_http import JurixHttpClient
from .models import AccountStatus, AuthSession
from .repository import AccountRepository, utcnow

TITLE_TOKEN_PATTERN = re.compile(r"[0-9A-Za-zÇĞİÖŞÜçğıöşü]+", re.UNICODE)
TITLE_SEARCH_STOPWORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "article",
        "articles",
        "bakimindan",
        "bir",
        "bu",
        "by",
        "da",
        "de",
        "dair",
        "en",
        "find",
        "for",
        "gibi",
        "gore",
        "hakkinda",
        "icin",
        "ile",
        "in",
        "into",
        "jurix",
        "konusunda",
        "looking",
        "lütfen",
        "makale",
        "makaleler",
        "mi",
        "mı",
        "mu",
        "mü",
        "not",
        "olan",
        "olarak",
        "or",
        "please",
        "related",
        "search",
        "the",
        "ve",
        "veya",
        "with",
        "yazı",
        "yazi",
    }
)
MAX_TITLE_KEYWORDS = 6
MAX_QUERY_TOKENS = 8
MAX_QUERY_CHARS = 80
MIN_QUERY_TERM_LENGTH = 3


class JurixToolService:
    def __init__(self, account_manager: AccountManager, jurix_client: JurixHttpClient, repository: AccountRepository):
        self.account_manager = account_manager
        self.jurix_client = jurix_client
        self.repository = repository

    def jurix_search(self, query: str, limit: int | None = None) -> dict[str, Any]:
        query_info = self._normalize_search_query(query)
        pool_status = self.jurix_pool_status()
        if query_info["status"] != "ok":
            return {
                "status": "invalid_query",
                "search_type": "title_keyword_search",
                "query": query_info,
                "results": [],
                "result_count": 0,
                "pool_status": pool_status,
                "next_actions": self._build_search_next_actions("invalid_query", pool_status),
            }

        try:
            auth = self.account_manager.get_valid_auth_session()
        except (AccountPoolError, AuthenticationError) as exc:
            raise type(exc)(
                f"{exc}. Call jurix_pool_status to inspect the pool, then jurix_ensure_pool if Jurix is empty or unhealthy."
            ) from exc

        session = self.jurix_client.new_session(auth.user_agent, auth.cookies)
        results = self.jurix_client.search(session, query_info["normalized"], limit)
        payload = [asdict(item) for item in results]
        pool_status = self.jurix_pool_status()
        search_status = "ok" if payload else "no_results"
        return {
            "status": search_status,
            "search_type": "title_keyword_search",
            "search_field": "title",
            "query": query_info,
            "results": payload,
            "result_count": len(payload),
            "pool_status": pool_status,
            "next_actions": self._build_search_next_actions(search_status, pool_status),
        }

    def jurix_download_pdf(self, article_id: str) -> dict:
        auth = self.account_manager.get_valid_auth_session()
        session = self.jurix_client.new_session(auth.user_agent, auth.cookies)
        output_root = self.account_manager.settings.download_root
        output_root.mkdir(parents=True, exist_ok=True)
        try:
            result = self.jurix_client.download_article_pdf(session, article_id, output_root)
        except DownloadError as exc:
            # Some article pages hide page-image slug when the cookie is stale but still looks logged in.
            if "Unable to extract image slug from article page" not in str(exc):
                self.repository.upsert_download_failure(source="jurix", article_id=article_id, error_message=str(exc))
                raise
            try:
                fresh_session = self._force_relogin_session(auth)
            except AuthenticationError:
                # If the selected account credentials are no longer accepted, rotate to another valid account.
                fallback_auth = self.account_manager.get_valid_auth_session()
                fresh_session = self.jurix_client.new_session(fallback_auth.user_agent, fallback_auth.cookies)
            try:
                result = self.jurix_client.download_article_pdf(fresh_session, article_id, output_root)
            except Exception as retry_exc:
                self.repository.upsert_download_failure(source="jurix", article_id=article_id, error_message=str(retry_exc))
                raise
        except Exception as exc:
            self.repository.upsert_download_failure(source="jurix", article_id=article_id, error_message=str(exc))
            raise
        self.repository.upsert_download_success(result)
        return result.as_dict()

    def _force_relogin_session(self, auth: AuthSession):
        session = self.jurix_client.new_session(auth.user_agent)
        csrf = self.jurix_client.bootstrap_csrf(session)
        csrf = self.jurix_client.login(session, auth.account.email, auth.account.password, csrf)
        self.repository.save_session(
            account_id=auth.account.id,
            csrf_token=csrf,
            cookies=session.cookies.get_dict(),
            user_agent=session.headers.get("User-Agent", self.account_manager.settings.default_user_agent),
            is_valid=True,
        )
        return session

    def jurix_ensure_pool(self) -> dict:
        ready_before = self.repository.count_ready_accounts(self.account_manager.settings.account_expiry_buffer_hours)
        self.account_manager.ensure_pool_size()
        summary = self.jurix_pool_status()
        summary["ready_accounts_before"] = ready_before
        summary["ready_accounts_after"] = summary["ready_accounts"]
        summary["message"] = "Use this when Jurix search/download responses are unexpectedly empty or the pool is below target."
        return summary

    def jurix_pool_status(self) -> dict[str, Any]:
        ready_accounts = self.repository.count_ready_accounts(self.account_manager.settings.account_expiry_buffer_hours)
        accounts_by_status = self.repository.count_accounts_by_status()
        normalized_counts = {status.value: accounts_by_status.get(status.value, 0) for status in AccountStatus}
        target_pool = self.account_manager.settings.account_pool_target
        return {
            "status": "ok",
            "ready_accounts": ready_accounts,
            "target_pool": target_pool,
            "healthy": ready_accounts >= target_pool,
            "expiry_buffer_hours": self.account_manager.settings.account_expiry_buffer_hours,
            "accounts_by_status": normalized_counts,
        }

    def jurix_account_status(self, email: str | None = None) -> dict[str, Any]:
        account = (
            self.repository.get_account_by_email(email)
            if email
            else self.repository.acquire_best_account(self.account_manager.settings.account_expiry_buffer_hours)
        )
        if account is None:
            return {
                "status": "not_found",
                "requested_email": email,
                "pool_status": self.jurix_pool_status(),
            }

        ready_cutoff = utcnow() + timedelta(hours=self.account_manager.settings.account_expiry_buffer_hours)
        session_record = self.repository.get_session_by_account_id(account.id)
        download_ready = (
            account.status == AccountStatus.ACTIVE and account.trial_expires_at > ready_cutoff
        )
        return {
            "status": "ok",
            "selected_by": "email" if email else "best_ready_account",
            "account": {
                "id": account.id,
                "email": account.email,
                "status": account.status.value,
                "trial_expires_at": account.trial_expires_at.isoformat(),
                "download_ready": download_ready,
                "last_used_at": account.last_used_at.isoformat() if account.last_used_at else None,
                "last_checked_at": account.last_checked_at.isoformat() if account.last_checked_at else None,
                "fail_count": account.fail_count,
            },
            "session": {
                "present": session_record is not None,
                "is_valid": session_record.is_valid if session_record else False,
                "updated_at": session_record.updated_at.isoformat() if session_record else None,
            },
            "pool_status": self.jurix_pool_status(),
        }

    def jurix_rotate_account(self) -> dict[str, Any]:
        previous = self.repository.acquire_best_account(self.account_manager.settings.account_expiry_buffer_hours)
        auth = self.account_manager.rotate_auth_session()
        pool_status = self.jurix_pool_status()
        return {
            "status": "ok",
            "rotated": previous is None or previous.email != auth.account.email,
            "previous_account_email": previous.email if previous else None,
            "current_account": {
                "id": auth.account.id,
                "email": auth.account.email,
                "status": auth.account.status.value,
                "trial_expires_at": auth.account.trial_expires_at.isoformat(),
            },
            "pool_status": pool_status,
            "message": "Use this before jurix_download_pdf when you want a different ready trial account.",
        }

    def jurix_download_status(self, article_id: str) -> dict:
        row = self.repository.get_download_by_article(source="jurix", article_id=article_id)
        if row is None:
            return {
                "source": "jurix",
                "article_id": article_id,
                "status": "not_found",
            }
        return {key: row[key] for key in row.keys()}

    def _normalize_search_query(self, query: str) -> dict[str, Any]:
        original = " ".join((query or "").split())
        if not original:
            return {
                "status": "invalid_query",
                "original": "",
                "normalized": "",
                "rewritten": False,
                "notes": [
                    "Jurix only supports short keyword searches on article titles. Retry with 2-6 title keywords.",
                ],
            }

        raw_tokens = TITLE_TOKEN_PATTERN.findall(original)
        filtered_tokens: list[str] = []
        seen_tokens: set[str] = set()
        for token in raw_tokens:
            folded = token.casefold()
            if len(folded) < MIN_QUERY_TERM_LENGTH:
                continue
            if folded in TITLE_SEARCH_STOPWORDS:
                continue
            if folded in seen_tokens:
                continue
            seen_tokens.add(folded)
            filtered_tokens.append(token)

        if not filtered_tokens:
            return {
                "status": "invalid_query",
                "original": original,
                "normalized": "",
                "rewritten": False,
                "notes": [
                    "No usable title keywords were found. Retry with 2-6 concrete Turkish keywords from the article title.",
                ],
            }

        looks_like_natural_language = (
            len(raw_tokens) > MAX_QUERY_TOKENS
            or len(original) > MAX_QUERY_CHARS
            or any(ch in original for ch in ".?!:\n")
        )
        normalized_tokens = filtered_tokens[:MAX_TITLE_KEYWORDS]
        normalized = " ".join(normalized_tokens)
        notes: list[str] = []
        rewritten = normalized != original

        if looks_like_natural_language:
            notes.append("Jurix does not support natural-language search. The query was reduced to short title keywords.")
            rewritten = True
        elif rewritten:
            notes.append("Stopwords, punctuation, or repeated terms were removed to keep the query title-focused.")

        if len(filtered_tokens) > MAX_TITLE_KEYWORDS:
            notes.append(f"Only the first {MAX_TITLE_KEYWORDS} distinct keywords were kept.")

        return {
            "status": "ok",
            "original": original,
            "normalized": normalized,
            "rewritten": rewritten,
            "notes": notes,
        }

    def _build_search_next_actions(self, status: str, pool_status: dict[str, Any]) -> list[str]:
        if status == "invalid_query":
            return [
                "Retry with 2-6 short Turkish keywords that are likely to appear in the article title.",
                "Do not send natural-language questions, long fact patterns, or paragraph summaries to jurix_search.",
            ]
        if status == "no_results":
            return [
                "Retry with 2-6 shorter Turkish title keywords or a narrower title phrase.",
                "Call jurix_pool_status if Jurix returned an empty page or no results unexpectedly.",
                "If the pool is unhealthy or Jurix still responds empty, call jurix_ensure_pool and rerun jurix_search.",
            ]
        if not pool_status["healthy"]:
            return [
                "jurix_search succeeded, but the account pool is below target. Call jurix_ensure_pool before heavier use.",
            ]
        return []
