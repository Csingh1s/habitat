from __future__ import annotations

from urllib.parse import urlparse

ALLOWED_HOSTS = {"discoverhorizon.com", "www.discoverhorizon.com"}
RISKY_WORDS = {
    "add", "approve", "book", "cancel", "create", "delete", "download", "edit",
    "export", "import", "insert", "print", "remove", "save", "send",
    "submit", "update", "upload",
}


def same_allowed_origin(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS


def risk_for(text: str, url: str = "") -> str:
    haystack = f"{text} {url}".lower()
    return "risky" if any(word in haystack for word in RISKY_WORDS) else "safe"


def may_navigate(url: str, confirmed_risky_urls: set[str]) -> tuple[bool, str]:
    if not same_allowed_origin(url):
        return False, "outside allowed Horizon HTTPS origin"
    if risk_for("", url) == "risky" and url not in confirmed_risky_urls:
        return False, "risky URL requires exact explicit confirmation"
    return True, ""
