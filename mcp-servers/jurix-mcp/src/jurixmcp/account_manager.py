from __future__ import annotations

import logging
import random
import string
import threading
import time
from datetime import timedelta

from .config import Settings
from .errors import AccountPoolError, AuthenticationError
from .jurix_http import JurixHttpClient
from .mail_provider import MailTmProvider
from .models import AccountStatus, AuthSession
from .repository import AccountRepository, utcnow

LOG = logging.getLogger("jurixmcp.account_manager")


class AccountManager:
    def __init__(
        self,
        settings: Settings,
        repository: AccountRepository,
        jurix_client: JurixHttpClient,
        mail_provider: MailTmProvider,
    ):
        self.settings = settings
        self.repository = repository
        self.jurix_client = jurix_client
        self.mail_provider = mail_provider
        self._pool_lock = threading.Lock()

    def ensure_pool_size(self) -> None:
        with self._pool_lock:
            ready = self.repository.count_ready_accounts(self.settings.account_expiry_buffer_hours)
            while ready < self.settings.account_pool_target:
                self.create_account_and_session()
                ready += 1

    def get_valid_auth_session(self) -> AuthSession:
        account = self.repository.acquire_best_account(self.settings.account_expiry_buffer_hours)
        if account is None:
            self.ensure_pool_size()
            account = self.repository.acquire_best_account(self.settings.account_expiry_buffer_hours)
            if account is None:
                raise AccountPoolError("No active accounts available after refill")

        session_record = self.repository.get_session_by_account_id(account.id)
        if session_record is None:
            return self._refresh_login(account.email, account.password, account.id)

        session = self.jurix_client.new_session(session_record.user_agent, session_record.cookies)
        if self.jurix_client.validate_session(session):
            self.repository.touch_account(account.email)
            return AuthSession(
                account=account,
                csrf_token=session_record.csrf_token,
                cookies=session_record.cookies,
                user_agent=session_record.user_agent,
            )

        self.repository.increment_fail_count(account.email)
        return self._refresh_login(account.email, account.password, account.id)

    def rotate_auth_session(self) -> AuthSession:
        current = self.repository.acquire_best_account(self.settings.account_expiry_buffer_hours)
        next_account = self.repository.acquire_best_account(
            self.settings.account_expiry_buffer_hours,
            exclude_email=current.email if current else None,
        )
        if next_account is None:
            return self.create_account_and_session()

        session_record = self.repository.get_session_by_account_id(next_account.id)
        if session_record is None:
            return self._refresh_login(next_account.email, next_account.password, next_account.id)

        session = self.jurix_client.new_session(session_record.user_agent, session_record.cookies)
        if self.jurix_client.validate_session(session):
            self.repository.touch_account(next_account.email)
            return AuthSession(
                account=next_account,
                csrf_token=session_record.csrf_token,
                cookies=session_record.cookies,
                user_agent=session_record.user_agent,
            )

        self.repository.increment_fail_count(next_account.email)
        return self._refresh_login(next_account.email, next_account.password, next_account.id)

    def _refresh_login(self, email: str, password: str, account_id: int) -> AuthSession:
        session = self.jurix_client.new_session()
        csrf = self.jurix_client.bootstrap_csrf(session)
        try:
            csrf = self.jurix_client.login(session, email, password, csrf)
        except AuthenticationError:
            self.repository.mark_status(email, AccountStatus.INVALID)
            self.repository.add_event(account_id, "account_invalid", {"email": email})
            raise

        self.repository.save_session(
            account_id=account_id,
            csrf_token=csrf,
            cookies=session.cookies.get_dict(),
            user_agent=session.headers.get("User-Agent", self.settings.default_user_agent),
            is_valid=True,
        )
        account = self.repository.get_account_by_email(email)
        if account is None:
            raise AccountPoolError("Account disappeared during refresh")
        self.repository.touch_account(email)
        self.repository.add_event(account.id, "session_refreshed", {"email": email})

        return AuthSession(
            account=account,
            csrf_token=csrf,
            cookies=session.cookies.get_dict(),
            user_agent=session.headers.get("User-Agent", self.settings.default_user_agent),
        )

    def retire_account(self, email: str, status: AccountStatus, reason: str) -> None:
        account = self.repository.get_account_by_email(email)
        self.repository.mark_status(email, status)
        self.repository.add_event(account.id if account else None, "account_retired", {"reason": reason, "status": status.value})

    def create_account_and_session(self) -> AuthSession:
        mail_account = self.mail_provider.create_account()
        jurix_password = "".join(random.choices(string.ascii_letters + string.digits + "!@#$%", k=14))
        first_name = "".join(random.choices(string.ascii_letters, k=6))
        last_name = "".join(random.choices(string.ascii_letters, k=6))

        session = self.jurix_client.new_session()
        csrf = self.jurix_client.bootstrap_csrf(session)
        self.jurix_client.register_trial(
            session=session,
            csrf_token=csrf,
            email=mail_account.email,
            password=jurix_password,
            first_name=first_name,
            last_name=last_name,
        )

        activation_link = self.mail_provider.poll_activation_link(
            token=mail_account.token,
            timeout_seconds=self.settings.mail_poll_timeout_seconds,
            interval_seconds=self.settings.mail_poll_interval_seconds,
        )
        self.jurix_client.activate(session, activation_link)
        if self.jurix_client.validate_session(session):
            page = session.get(self.settings.jurix_base_url, timeout=40)
            csrf = self.jurix_client.extract_csrf(page.text) or csrf
        else:
            last_exc: Exception | None = None
            for attempt in range(3):
                try:
                    csrf = self.jurix_client.login(session, mail_account.email, jurix_password, csrf)
                    last_exc = None
                    break
                except AuthenticationError as exc:
                    last_exc = exc
                    if attempt < 2:
                        time.sleep(4)
            if last_exc is not None:
                raise last_exc

        now = utcnow()
        account = self.repository.upsert_account(
            email=mail_account.email,
            password=jurix_password,
            created_at=now,
            trial_expires_at=now + timedelta(days=self.settings.trial_days),
            status=AccountStatus.ACTIVE,
        )
        self.repository.save_session(
            account_id=account.id,
            csrf_token=csrf,
            cookies=session.cookies.get_dict(),
            user_agent=session.headers.get("User-Agent", self.settings.default_user_agent),
            is_valid=True,
        )
        self.repository.touch_account(account.email)
        self.repository.add_event(account.id, "account_created", {"email": account.email})

        LOG.info("Account created", extra={"event": "account_created", "email": account.email, "status": account.status.value})

        return AuthSession(
            account=account,
            csrf_token=csrf,
            cookies=session.cookies.get_dict(),
            user_agent=session.headers.get("User-Agent", self.settings.default_user_agent),
        )
