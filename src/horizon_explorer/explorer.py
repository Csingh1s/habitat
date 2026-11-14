from __future__ import annotations

from collections import deque
from pathlib import Path
from urllib.parse import urldefrag
import json

from playwright.async_api import Browser, Page, async_playwright

from .models import Control, Evidence, Link, PageEvidence, utc_now
from .policy import may_navigate, risk_for, same_allowed_origin
from .report import markdown_report


EXTRACT_UI = """() => ({
  headings: Array.from(document.querySelectorAll('h1,h2,h3,[role="heading"]'), e => e.innerText.trim()).filter(Boolean),
  tabs: Array.from(document.querySelectorAll('[role="tab"], .tab, .tabs a'), e => e.innerText.trim()).filter(Boolean),
  forms: Array.from(document.forms, f => f.getAttribute('name') || f.id || 'unnamed form'),
  links: Array.from(document.querySelectorAll('a[href]'), a => ({text:a.innerText.trim(), url:a.href})),
  controls: Array.from(document.querySelectorAll('input,select,textarea,button'), e => ({
    kind:e.tagName.toLowerCase() === 'input' ? (e.type || 'input') : e.tagName.toLowerCase(),
    label:(e.labels && Array.from(e.labels, l => l.innerText.trim()).join(' ')) || e.getAttribute('aria-label') || e.innerText.trim() || '',
    name:e.getAttribute('name') || e.id || null,
    valueHint:e.getAttribute('placeholder') || null
  }))
})"""


async def inspect_page(page: Page) -> PageEvidence:
    raw = await page.evaluate(EXTRACT_UI)
    links = [Link(text=item["text"], url=item["url"], risk=risk_for(item["text"], item["url"])) for item in raw["links"]]
    controls = [
        Control(kind=item["kind"], label=item["label"], name=item["name"], value_hint=item["valueHint"],
                risk=risk_for(f"{item['kind']} {item['label']} {item['name'] or ''}"))
        for item in raw["controls"]
    ]
    return PageEvidence(url=page.url, title=await page.title(), headings=raw["headings"],
                        tabs=raw["tabs"], links=links, controls=controls, forms=raw["forms"])


async def crawl(cdp_url: str, start_url: str, output_dir: Path, max_pages: int,
                max_depth: int, confirmed_risky_urls: set[str]) -> Evidence:
    if not same_allowed_origin(start_url):
        raise ValueError("Start URL must be an HTTPS discoverhorizon.com URL.")
    if not cdp_url.startswith("http://127.0.0.1:") and not cdp_url.startswith("http://localhost:"):
        raise ValueError("CDP endpoint must be bound to localhost.")
    evidence = Evidence()
    queue = deque([(start_url, 0)])
    seen: set[str] = set()
    async with async_playwright() as playwright:
        browser: Browser = await playwright.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0]
        page = await context.new_page()
        try:
            while queue and len(evidence.pages) < max_pages:
                url, depth = queue.popleft()
                url = urldefrag(url).url
                if url in seen:
                    continue
                allowed, reason = may_navigate(url, confirmed_risky_urls)
                if not allowed:
                    evidence.blocked_items.append({"url": url, "reason": reason})
                    continue
                seen.add(url)
                await page.goto(url, wait_until="domcontentloaded")
                item = await inspect_page(page)
                evidence.pages.append(item)
                evidence.visited_pages.append({"url": page.url, "visited_at": utc_now(), "mode": "read-only inspection"})
                for link in item.links:
                    child_url = urldefrag(link.url).url
                    allowed, reason = may_navigate(child_url, confirmed_risky_urls)
                    if depth < max_depth and allowed and child_url not in seen:
                        queue.append((child_url, depth + 1))
                    elif not allowed:
                        evidence.blocked_items.append({"url": child_url, "reason": reason})
                for control in item.controls:
                    if control.risk == "risky":
                        evidence.blocked_items.append({"url": item.url, "reason": f"risky control not interacted with: {control.label or control.kind}"})
        finally:
            await page.close()
            # Do not close the browser: it is the user's manually authenticated session.
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "evidence.json").write_text(json.dumps(evidence.to_dict(), indent=2), encoding="utf-8")
    (output_dir / "requirements.md").write_text(markdown_report(evidence), encoding="utf-8")
    return evidence
