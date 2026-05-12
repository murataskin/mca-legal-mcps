from __future__ import annotations

from fastmcp import FastMCP

from .account_manager import AccountManager
from .config import get_settings
from .jurix_http import JurixHttpClient
from .logging_utils import configure_logging
from .mail_provider import MailTmProvider
from .repository import AccountRepository
from .tools import JurixToolService


def create_mcp() -> FastMCP:
    configure_logging()
    settings = get_settings()
    repository = AccountRepository(settings.database_path)
    jurix_client = JurixHttpClient(settings.jurix_base_url, settings.default_user_agent)
    mail_provider = MailTmProvider(settings.mailtm_base_url)
    account_manager = AccountManager(settings, repository, jurix_client, mail_provider)
    tool_service = JurixToolService(account_manager, jurix_client, repository)

    mcp = FastMCP("Jurix MCP Server")

    @mcp.tool
    def jurix_search(query: str, limit: int | None = None) -> dict:
        """Search Jurix article titles with 2-6 short keywords, not natural-language prompts.

        Jurix search is keyword-based and title-focused. Use concise Turkish title keywords such as
        "anonim şirket huzur hakkı" or "kira tespit". Do not send questions, long summaries, or fact patterns.

        If the response is unexpectedly empty, inspect jurix_pool_status and call jurix_ensure_pool before retrying.
        """
        return tool_service.jurix_search(query, limit)

    @mcp.tool
    def jurix_download_pdf(article_id: str) -> dict:
        """Download a Jurix article and return generated PDF metadata."""
        return tool_service.jurix_download_pdf(article_id)

    @mcp.tool
    def jurix_pool_status() -> dict:
        """Report Jurix account-pool health. Use this when search/download responses are empty or suspicious."""
        return tool_service.jurix_pool_status()

    @mcp.tool
    def jurix_ensure_pool() -> dict:
        """Refill Jurix account pool to target size. Use this after jurix_pool_status shows an unhealthy pool."""
        return tool_service.jurix_ensure_pool()

    @mcp.tool
    def jurix_account_status(email: str | None = None) -> dict:
        """Inspect the selected or requested account and report whether it is still ready for downloads."""
        return tool_service.jurix_account_status(email)

    @mcp.tool
    def jurix_rotate_account() -> dict:
        """Switch to a different ready account. Creates a fresh trial account if no alternative exists."""
        return tool_service.jurix_rotate_account()

    @mcp.tool
    def jurix_download_status(article_id: str) -> dict:
        """Return persisted download status/metadata for a Jurix article id."""
        return tool_service.jurix_download_status(article_id)

    return mcp


def main():
    mcp = create_mcp()
    mcp.run()
