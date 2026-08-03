"""Print the US symbols reporting earnings today, comma-separated.

The daily fundamentals refresh runs off announcements rather than a timer, and this is the
complete signal for the US market - stockanalysis lists every company reporting on the day.
PSX gets the same completeness from exchange announcements in catalysts.json; the other markets
have no equivalent feed, which is why the refresh also carries a staleness backstop.

The page has no usable date navigation (a ?date= parameter is ignored and dated paths 404), so
this reads "today" and the refresh job runs daily - a company reporting today is picked up by
tomorrow's run, which is exactly the intended cadence.

    python scripts/earnings_calendar.py            # today's reporters
"""

from __future__ import annotations

import sys

URL = "https://stockanalysis.com/stocks/earnings-calendar/"
SKIP_RESOURCES = {"image", "media", "font", "stylesheet"}


def fetch(timeout_ms: int = 30000) -> list[str]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = browser.new_context(
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            )
            ctx.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in SKIP_RESOURCES
                else route.continue_(),
            )
            page = ctx.new_page()
            resp = page.goto(URL, wait_until="domcontentloaded", timeout=timeout_ms)
            if not resp or resp.status >= 400:
                return []
            # The table is client-rendered; wait for rows rather than for the element, which
            # exists empty.
            page.wait_for_function(
                "() => [...document.querySelectorAll('table')]"
                ".some(t => t.querySelectorAll('tbody tr').length > 0)",
                timeout=20000,
            )
            return page.evaluate("""() => {
                const tables = [...document.querySelectorAll('table')];
                if (!tables.length) return [];
                const t = tables.reduce((a, b) =>
                    b.querySelectorAll('tbody tr').length >
                    a.querySelectorAll('tbody tr').length ? b : a);
                return [...t.querySelectorAll('tbody tr')]
                    .map(r => (r.querySelector('td')?.innerText || '').trim())
                    .filter(s => /^[A-Z][A-Z.\\-]{0,6}$/.test(s));
            }""")
        except Exception:  # noqa: BLE001 - a blocked calendar must not fail the refresh
            return []
        finally:
            browser.close()


def main() -> int:
    print(",".join(sorted(set(fetch()))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
