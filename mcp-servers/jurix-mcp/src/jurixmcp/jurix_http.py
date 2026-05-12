from __future__ import annotations

import logging
import re
import time
from io import BytesIO
from pathlib import Path
import hashlib
import json

import requests
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

from .errors import AuthenticationError, DownloadError, RegistrationError
from .models import DownloadResult, SearchResult

LOG = logging.getLogger("jurixmcp.jurix_http")


class JurixHttpClient:
    def __init__(self, base_url: str, default_user_agent: str):
        self.base_url = base_url.rstrip("/")
        self.default_user_agent = default_user_agent

    def new_session(self, user_agent: str | None = None, cookies: dict[str, str] | None = None) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": user_agent or self.default_user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )
        if cookies:
            session.cookies.update(cookies)
        return session

    def bootstrap_csrf(self, session: requests.Session) -> str:
        response = session.get(self.base_url, timeout=40)
        response.raise_for_status()
        csrf = self.extract_csrf(response.text)
        if csrf:
            return csrf

        response = session.get(f"{self.base_url}/register_trial", timeout=40)
        response.raise_for_status()
        csrf = self.extract_csrf(response.text)
        if not csrf:
            raise AuthenticationError("Unable to bootstrap CSRF token")
        return csrf

    @staticmethod
    def extract_csrf(html: str) -> str | None:
        soup = BeautifulSoup(html, "html.parser")
        token = soup.find("meta", {"name": "csrf-token"})
        if token:
            return token.get("content")
        token = soup.find("input", {"name": "_token"})
        if token:
            return token.get("value")
        return None

    def register_trial(
        self,
        session: requests.Session,
        csrf_token: str,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
    ) -> None:
        payload = {
            "_token": csrf_token,
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "password": password,
            "password2": password,
        }
        response = session.post(
            f"{self.base_url}/register_trial",
            data=payload,
            headers={
                "Origin": self.base_url,
                "Referer": f"{self.base_url}/",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=40,
        )
        if response.status_code not in (200, 302):
            LOG.error(
                "Registration failed",
                extra={
                    "event": "registration_failed",
                    "detail": f"status={response.status_code} body={response.text[:300]!r}",
                },
            )
            raise RegistrationError(f"Registration failed with status {response.status_code}")

    def activate(self, session: requests.Session, activation_link: str) -> None:
        response = session.get(activation_link, timeout=40)
        if response.status_code not in (200, 302):
            LOG.error(
                "Activation failed",
                extra={
                    "event": "activation_failed",
                    "detail": f"status={response.status_code} link={activation_link}",
                },
            )
            raise RegistrationError(f"Activation failed with status {response.status_code}")

    def login(self, session: requests.Session, email: str, password: str, fallback_csrf: str) -> str:
        login_url = f"{self.base_url}/login"
        response = session.get(login_url, timeout=40)
        response.raise_for_status()
        csrf = self.extract_csrf(response.text) or fallback_csrf
        clean_email = email.strip()

        # HAR flow: /login is called as JSON XHR and returns "redirect_required" on success.
        ajax_response = session.post(
            login_url,
            data=json.dumps({"email": clean_email, "password": password}, ensure_ascii=True),
            headers={
                "Accept": "application/json, text/plain, */*",
                "Origin": self.base_url,
                "Referer": login_url,
                "Content-Type": "application/json;charset=utf-8",
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRF-TOKEN": csrf,
            },
            timeout=40,
        )
        if ajax_response.status_code == 200:
            ajax_body = (ajax_response.text or "").strip().strip('"').lower()
            if ajax_body == "redirect_required" or self.validate_session(session):
                return csrf
            if "hatal" in ajax_response.text.lower() and "giri" in ajax_response.text.lower():
                LOG.error(
                    "Login rejected",
                    extra={
                        "event": "login_rejected",
                        "detail": f"email={clean_email} body={ajax_response.text[:300]!r}",
                    },
                )
                raise AuthenticationError("Login failed due to invalid credentials")

        payload = {
            "_token": csrf,
            "email": clean_email,
            "password": password,
            "from": login_url,
        }
        response = session.post(
            login_url,
            data=payload,
            headers={
                "Origin": self.base_url,
                "Referer": login_url,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=40,
        )

        if response.status_code not in (200, 302):
            LOG.error(
                "Login failed",
                extra={
                    "event": "login_failed",
                    "detail": (
                        f"ajax_status={ajax_response.status_code} ajax_body={ajax_response.text[:120]!r} "
                        f"status={response.status_code} body={response.text[:300]!r}"
                    ),
                },
            )
            raise AuthenticationError(f"Login failed with status {response.status_code}")
        if response.status_code == 200 and "Hatal" in response.text and "Giri" in response.text:
            LOG.error(
                "Login rejected",
                extra={
                    "event": "login_rejected",
                    "detail": f"email={clean_email} body={response.text[:300]!r}",
                },
            )
            raise AuthenticationError("Login failed due to invalid credentials")

        return csrf

    def validate_session(self, session: requests.Session) -> bool:
        response = session.get(self.base_url, timeout=30)
        if response.status_code != 200:
            return False
        body = response.text.lower()

        # HAR marker: user-menu exists in both states; false means not authenticated.
        if ':logged-in-user="false"' in body or ":logged-in-user='false'" in body:
            return False
        if re.search(r':logged-in-user\s*=\s*["\']\{', body):
            return True

        logged_in_markers = ("hesab", "cikis yap", "cÄ±kÄ±s yap", "logout")
        logged_out_markers = ("giris yap", "giriÅŸ yap", "/login")
        if any(marker in body for marker in logged_out_markers):
            return False
        if any(marker in body for marker in logged_in_markers):
            return True
        return "laravel_session" in session.cookies.get_dict()

    def search(self, session: requests.Session, query: str, limit: int | None = None) -> list[SearchResult]:
        response = session.get(
            f"{self.base_url}/dons",
            params={"q[0]": query, "q[1]": "", "q[2]": ""},
            timeout=40,
        )
        response.raise_for_status()
        return self.parse_search_results(response.text, self.base_url, limit)

    @staticmethod
    def parse_search_results(html: str, base_url: str, limit: int | None = None) -> list[SearchResult]:
        soup = BeautifulSoup(html, "html.parser")
        results_container = soup.find("ul", class_="result")
        if not results_container:
            return []

        items: list[SearchResult] = []
        title_tags = results_container.find_all("h3", class_="resultArticleTitle")
        for title_tag in title_tags:
            if limit is not None and len(items) >= limit:
                break
            anchor = title_tag.find("a")
            if not anchor:
                continue
            href = str(anchor.get("href", ""))
            full_link = href if href.startswith("http") else f"{base_url}{href}"
            article_id = None
            path = href.split("?")[0].split("/")
            if len(path) > 2 and path[1] == "article":
                article_id = path[2]

            meta_text = None
            author = None
            journal = None
            issue_date = None
            summary_ul = title_tag.find_next_sibling("ul", class_="summary")
            if summary_ul:
                meta_text = summary_ul.get_text(strip=True)
                parts = [p.strip() for p in meta_text.split("|")]
                if len(parts) > 0:
                    author = parts[0]
                if len(parts) > 1:
                    journal = parts[1]
                if len(parts) > 2:
                    issue_date = parts[2]

            snippet = None
            current = title_tag
            for _ in range(5):
                current = current.find_next_sibling()
                if current is None:
                    break
                if getattr(current, "name", None) == "div":
                    node = current.find("p", class_="resultSummary")
                    if node:
                        snippet = node.get_text(strip=True)
                        break

            items.append(
                SearchResult(
                    id=article_id,
                    title=anchor.get_text(strip=True),
                    link=full_link,
                    author=author,
                    journal=journal,
                    issue_date=issue_date,
                    metadata_raw=meta_text,
                    snippet=snippet,
                )
            )
        return items

    def get_article_details(self, session: requests.Session, article_id: str) -> dict:
        article_url = f"{self.base_url}/article/{article_id}"
        response = session.get(article_url, timeout=40)
        response.raise_for_status()
        html = response.text
        soup = BeautifulSoup(html, "html.parser")

        title = soup.find("meta", property="name") or soup.find("meta", property="headline") or soup.find(class_="articleTitle")
        title_text = title.get("content") if title and title.get("content") else (title.get_text(strip=True) if title else f"Article_{article_id}")

        author = soup.find("meta", property="author")
        author_text = author.get("content") if author and author.get("content") else "Unknown_Author"

        journal_name = self._extract_first_text(soup, "a[href*='/journal/']", ".issuejournal")
        editor = self._extract_value_after_label(soup, "EditÃ¶r")
        issn = self._extract_value_after_label(soup, "ISSN")
        volume, issue, issue_label = self._extract_issue_info(soup)
        published_start_page, published_end_page = self._extract_published_page_range(soup, html)

        start_page = None
        end_page = None
        page_start = soup.find("span", property="pageStart")
        page_end = soup.find("span", property="pageEnd")
        if page_start and page_end:
            try:
                start_page = int(page_start.get_text(strip=True))
                end_page = int(page_end.get_text(strip=True))
            except ValueError:
                start_page = None
                end_page = None

        if start_page is None or end_page is None:
            if published_start_page is not None and published_end_page is not None:
                start_page = published_start_page
                end_page = published_end_page

        if start_page is None or end_page is None:
            start_page = 1
            end_page = 10

        slug = None
        for script in soup.find_all("script"):
            script_text = script.string or ""
            match = re.search(r"image\.src\s*=\s*'/getpageimage/'\s*\+\s*page\s*\+\s*'/([\w]+)(/p)?';", script_text)
            if match:
                slug = match.group(1)
                break
        if slug is None:
            img_match = re.search(r"/getpageimage/\d+/([\w]+)(?:\?|\"|')", html)
            if img_match:
                slug = img_match.group(1)
        if slug is None:
            raise DownloadError("Unable to extract image slug from article page")

        image_pages = self._extract_image_pages_from_html(html, slug)
        if image_pages:
            start_page, end_page = min(image_pages), max(image_pages)
        else:
            start_page, end_page = self._resolve_page_range(session, slug, start_page, end_page)

        return {
            "id": article_id,
            "article_url": article_url,
            "title": title_text,
            "author": author_text,
            "journal_name": journal_name,
            "editor": editor,
            "issn": issn,
            "volume": volume,
            "issue": issue,
            "issue_label": issue_label,
            "published_start_page": published_start_page,
            "published_end_page": published_end_page,
            "start_page": start_page,
            "end_page": end_page,
            "slug": slug,
        }

    def download_article_pdf(self, session: requests.Session, article_id: str, output_root: Path) -> DownloadResult:
        started = time.perf_counter()
        details = self.get_article_details(session, article_id)
        safe_title = "".join(c for c in details["title"][:50] if c.isalnum() or c in (" ", "-")).strip().replace(" ", "_")
        safe_author = "".join(c for c in details["author"][:20] if c.isalnum() or c in (" ", "-")).strip().replace(" ", "_")
        folder_name = f"{safe_title}_{safe_author}_{details['id']}"
        article_dir = output_root / folder_name
        article_dir.mkdir(parents=True, exist_ok=True)

        image_paths: list[Path] = []
        for page_num in range(details["start_page"], details["end_page"] + 1):
            content = self._download_image_with_retry(session, page_num, details["slug"])
            if content is None:
                continue
            try:
                image = Image.open(BytesIO(content)).convert("RGB")
            except (UnidentifiedImageError, OSError):
                LOG.warning(
                    "Skipping non-image page payload",
                    extra={
                        "event": "page_payload_not_image",
                        "detail": f"article_id={article_id} page={page_num} bytes={len(content)}",
                    },
                )
                continue
            path = article_dir / f"page_{page_num:03d}.png"
            image.save(path, "PNG")
            image_paths.append(path)

        if not image_paths:
            raise DownloadError("No pages downloaded")

        pdf_path = article_dir / f"{article_dir.name}.pdf"
        images = [Image.open(path).convert("RGB") for path in image_paths]
        try:
            images[0].save(pdf_path, "PDF", resolution=100.0, save_all=True, append_images=images[1:])
        finally:
            for image in images:
                image.close()

        download_start_page = int(details["start_page"])
        download_end_page = int(details["end_page"])
        pdf_size_bytes = int(pdf_path.stat().st_size)
        pdf_sha256 = self._sha256_file(pdf_path)
        download_duration_ms = int((time.perf_counter() - started) * 1000)

        return DownloadResult(
            source="jurix",
            article_id=str(details["id"]),
            article_url=str(details["article_url"]),
            title=str(details["title"]),
            author=str(details["author"]),
            journal_name=str(details["journal_name"]) if details["journal_name"] else None,
            editor=str(details["editor"]) if details["editor"] else None,
            issn=str(details["issn"]) if details["issn"] else None,
            volume=int(details["volume"]) if details["volume"] is not None else None,
            issue=int(details["issue"]) if details["issue"] is not None else None,
            issue_label=str(details["issue_label"]) if details["issue_label"] else None,
            published_start_page=int(details["published_start_page"]) if details["published_start_page"] is not None else None,
            published_end_page=int(details["published_end_page"]) if details["published_end_page"] is not None else None,
            download_start_page=download_start_page,
            download_end_page=download_end_page,
            downloaded_page_count=len(image_paths),
            download_duration_ms=download_duration_ms,
            download_dir=str(article_dir),
            pdf_filename=pdf_path.name,
            pdf_size_bytes=pdf_size_bytes,
            pdf_sha256=pdf_sha256,
            start_page=int(details["start_page"]),
            end_page=int(details["end_page"]),
            slug=str(details["slug"]),
            page_count=len(image_paths),
            pdf_path=str(pdf_path),
        )

    def _download_image_with_retry(self, session: requests.Session, page_num: int, slug: str) -> bytes | None:
        base = f"{self.base_url}/getpageimage/{page_num}/{slug}"
        for url in (base, f"{base}/p"):
            try:
                response = session.get(url, timeout=30)
                if response.status_code == 200 and self._looks_like_image_response(response):
                    return response.content
            except requests.RequestException:
                continue
        return None

    def _resolve_page_range(
        self,
        session: requests.Session,
        slug: str,
        start_hint: int,
        end_hint: int,
        window: int = 5,
    ) -> tuple[int, int]:
        start = max(1, int(start_hint))
        end = max(start, int(end_hint))

        # Validate around the hinted start; fix common off-by-one or shifted values.
        if self._image_exists(session, start, slug):
            for _ in range(window):
                if start > 1 and self._image_exists(session, start - 1, slug):
                    start -= 1
                else:
                    break
        else:
            for delta in range(1, window + 1):
                candidate = start + delta
                if self._image_exists(session, candidate, slug):
                    start = candidate
                    break

        # Validate around the hinted end.
        if self._image_exists(session, end, slug):
            for _ in range(window):
                if self._image_exists(session, end + 1, slug):
                    end += 1
                else:
                    break
        else:
            for delta in range(1, window + 1):
                candidate = end - delta
                if candidate >= start and self._image_exists(session, candidate, slug):
                    end = candidate
                    break

        if end < start:
            end = start
        return start, end

    def _image_exists(self, session: requests.Session, page_num: int, slug: str) -> bool:
        if page_num < 1:
            return False
        base = f"{self.base_url}/getpageimage/{page_num}/{slug}"
        for url in (base, f"{base}/p"):
            try:
                response = session.get(url, timeout=15)
                if response.status_code == 200 and self._looks_like_image_response(response):
                    return True
            except requests.RequestException:
                continue
        return False

    @staticmethod
    def _looks_like_image_response(response: requests.Response) -> bool:
        content = response.content or b""
        if not content:
            return False

        content_type = (response.headers.get("Content-Type") or "").lower()
        if content_type.startswith("image/"):
            return True

        head = content[:128].lstrip().lower()
        if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
            return False

        return content.startswith(b"\x89PNG\r\n\x1a\n") or content.startswith(b"\xff\xd8\xff")

    @staticmethod
    def _extract_image_pages_from_html(html: str, slug: str) -> list[int]:
        pattern = rf"/getpageimage/(\d+)/{re.escape(slug)}(?:\?|\"|')"
        pages = [int(x) for x in re.findall(pattern, html)]
        return sorted(set(pages))

    @staticmethod
    def _extract_first_text(soup: BeautifulSoup, *selectors: str) -> str | None:
        for selector in selectors:
            node = soup.select_one(selector)
            if not node:
                continue
            text = node.get_text(" ", strip=True)
            if text:
                return text
        return None

    @staticmethod
    def _extract_value_after_label(soup: BeautifulSoup, label: str) -> str | None:
        pattern = re.compile(rf"{re.escape(label)}\s*:\s*(.+)")
        for li in soup.find_all("li"):
            text = li.get_text(" ", strip=True)
            match = pattern.search(text)
            if match:
                value = match.group(1).strip()
                return value or None
        return None

    @staticmethod
    def _extract_issue_info(soup: BeautifulSoup) -> tuple[int | None, int | None, str | None]:
        for li in soup.find_all("li"):
            text = li.get_text(" ", strip=True)
            if "Cilt" not in text and "SayÄ±" not in text:
                continue
            volume_match = re.search(r"Cilt\s*:\s*(\d+)", text)
            issue_match = re.search(r"SayÄ±\s*:\s*(\d+)", text)
            label_match = re.search(r"SayÄ±\s*:\s*\d+\s*\|\s*(.+)$", text)
            volume = int(volume_match.group(1)) if volume_match else None
            issue = int(issue_match.group(1)) if issue_match else None
            issue_label = label_match.group(1).strip() if label_match else None
            return volume, issue, issue_label
        return None, None, None

    @staticmethod
    def _extract_published_page_range(soup: BeautifulSoup, html: str) -> tuple[int | None, int | None]:
        for li in soup.find_all("li"):
            text = li.get_text(" ", strip=True)
            match = re.search(r"Makalenin\s+YayÄ±nlandÄ±ÄŸÄ±\s+Sayfa\s*:\s*(\d+)\s*-\s*(\d+)", text, flags=re.IGNORECASE)
            if match:
                return int(match.group(1)), int(match.group(2))

        content_option = soup.find(class_="content-option")
        if content_option:
            match = re.search(r"Sayfa:\s*(\d+)-(\d+)", content_option.get_text(" ", strip=True))
            if match:
                return int(match.group(1)), int(match.group(2))

        cite_match = re.search(r"Sayfa:\s*(\d+)\s*-\s*(\d+)", html)
        if cite_match:
            return int(cite_match.group(1)), int(cite_match.group(2))
        return None, None

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
