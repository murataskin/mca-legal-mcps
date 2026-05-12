from __future__ import annotations

import random
import re
import string
import time
from dataclasses import dataclass

import requests


@dataclass(slots=True)
class MailAccount:
    email: str
    password: str
    token: str


class MailTmProvider:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str, **kwargs):
        response = requests.request(method, f"{self.base_url}{path}", timeout=40, **kwargs)
        response.raise_for_status()
        return response

    def create_account(self) -> MailAccount:
        domains = self._request("GET", "/domains").json().get("hydra:member", [])
        if not domains:
            raise RuntimeError("mail.tm returned no domains")
        domain = domains[0]["domain"]

        username = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        password = "".join(random.choices(string.ascii_letters + string.digits, k=16))
        email = f"{username}@{domain}"

        self._request(
            "POST",
            "/accounts",
            headers={"Content-Type": "application/json"},
            json={"address": email, "password": password},
        )

        token = self._request(
            "POST",
            "/token",
            headers={"Content-Type": "application/json"},
            json={"address": email, "password": password},
        ).json()["token"]

        return MailAccount(email=email, password=password, token=token)

    def poll_activation_link(
        self,
        token: str,
        timeout_seconds: int,
        interval_seconds: int,
    ) -> str:
        deadline = time.time() + timeout_seconds
        headers = {"Authorization": f"Bearer {token}"}

        while time.time() < deadline:
            messages = self._request("GET", "/messages", headers=headers).json().get("hydra:member", [])
            for message in messages:
                message_id = message.get("id") or str(message.get("@id", "")).split("/")[-1]
                if not message_id:
                    continue
                detail = self._request("GET", f"/messages/{message_id}", headers=headers).json()
                html_parts = detail.get("html") or []
                text = detail.get("text") or ""
                blobs = [*html_parts, text]
                for blob in blobs:
                    for url in re.findall(r'https?://[^\s<>"]+', blob):
                        lower_url = url.lower()
                        if "activat" in lower_url or "verify" in lower_url or "dogrula" in lower_url:
                            return url
            time.sleep(interval_seconds)

        raise TimeoutError("Activation email not received before timeout")
