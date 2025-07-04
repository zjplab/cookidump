#!/usr/bin/python3
"""
planner.py – Cookidoo recipe-URL planner

Given a list of search keywords, it logs in once, runs each query, grabs up to
`--max-per-keyword` (default 1000) unique recipe URLs per keyword and stores
all of them in a JSON file.  This file will later be consumed by
`downloader.py`.
"""

import os
import io
import re
import json
import time
import argparse
from urllib.parse import urlparse
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
PAGELOAD_TO = 3      # seconds to wait after navigation/click
SCROLL_TO   = 1      # seconds between scrolls during infinite-scroll collection
MAX_SCROLL_RETRIES = 5  # stop if no new tiles appear after N scrolls

# ---------------------------------------------------------------------------
# Utility helpers (shared with downloader.py)
# ---------------------------------------------------------------------------

def start_browser(chrome_driver_path):
    """Return a Selenium Chrome WebDriver with basic options enabled."""
    chrome_options = Options()
    if "GOOGLE_CHROME_PATH" in os.environ:
        chrome_options.binary_location = os.getenv("GOOGLE_CHROME_PATH")
    # comment the following line if you want to see the browser GUI
    # chrome_options.add_argument("--headless=new")
    service = Service(chrome_driver_path)
    return webdriver.Chrome(service=service, options=chrome_options)


def _infinite_scroll_collect(browser, max_expected):
    """Return at most `max_expected` recipe links currently present on page."""
    collected = set()
    previous_count = 0
    retry_counter   = 0

    while len(collected) < max_expected:
        # collect current batch
        for el in browser.find_elements(By.CLASS_NAME, "link--alt"):
            href = el.get_attribute("href")
            if href and "recipe" in href:
                collected.add(href)
        # break if target reached
        if len(collected) >= max_expected:
            break

        # infinite scroll to bottom
        browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SCROLL_TO)

        # click explicit "加载更多食谱" button if present
        try:
            load_more = browser.find_element(By.CSS_SELECTOR, 'button[data-cy="load-more-button"]')
            if load_more.is_displayed():
                browser.execute_script("arguments[0].click();", load_more)
                time.sleep(PAGELOAD_TO)
        except Exception:
            pass  # ignore if not found

        # detect no-new-tiles condition
        retry_counter = retry_counter + 1 if len(collected) == previous_count else 0
        if retry_counter >= MAX_SCROLL_RETRIES:
            break
        previous_count = len(collected)

    return list(collected)[:max_expected]


def collect_urls_for_keyword(browser, base_search_url, keyword, max_per_keyword):
    """Run a search for the given keyword and return up to max_per_keyword URLs."""
    print(f"[PLANNER] → keyword: '{keyword}'")

    # Locate search input, clear, & submit new query via UI to preserve possible filters.
    try:
        search_input = browser.find_element(By.CSS_SELECTOR, "input[type='search']")
    except Exception:
        raise RuntimeError("Cannot locate search input – please make sure you are on a Cookidoo search page.")

    # clear and enter keyword
    search_input.clear()
    search_input.send_keys(Keys.CONTROL, 'a')
    search_input.send_keys(keyword)
    search_input.send_keys(Keys.ENTER)
    time.sleep(PAGELOAD_TO)

    # first page: collect with infinite scroll logic
    urls = _infinite_scroll_collect(browser, max_per_keyword)

    # paginate further if necessary
    page_num = 2
    consecutive_empty = 0

    # Build a clean base url without existing &page=N so we can append ours
    _clean = re.sub(r"[&?]page=\d+", "", browser.current_url.split('#')[0])
    page_delim = '&' if '?' in _clean else '?'

    while len(urls) < max_per_keyword and consecutive_empty < 2:
        page_url = f"{_clean}{page_delim}page={page_num}"
        print(f"[PLANNER] Visiting {page_url}")
        browser.get(page_url)
        time.sleep(PAGELOAD_TO)

        new_urls = _infinite_scroll_collect(browser, max_per_keyword - len(urls))
        added = 0
        for u in new_urls:
            if u not in urls:
                urls.append(u)
                added += 1
        print(f"[PLANNER] page {page_num}: +{added} (total {len(urls)})")

        consecutive_empty = consecutive_empty + 1 if added == 0 else 0
        page_num += 1

    return urls

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Cookidoo planner – collect recipe URLs in batches \n"  # noqa: E501
                                     "so that each query returns ≤ 1000 items (site limit).")
    parser.add_argument('webdriver', type=str, help='Path to Chrome WebDriver')
    parser.add_argument('keywords', type=str, help='Text file with one search keyword per line')
    parser.add_argument('output',   type=str, help='Path to output JSON file (list of URLs)')
    parser.add_argument('--max-per-keyword', type=int, default=1000,
                        help='Upper bound of URLs to collect per keyword (default 1000)')

    args = parser.parse_args()

    # Prepare
    keywords = [k.strip() for k in Path(args.keywords).read_text(encoding='utf-8').splitlines() if k.strip()]
    all_urls = set()

    # Launch browser & navigate to generic search page
    base_search_url = 'https://cookidoo.com.cn/search/zh-Hans-CN?languages=zh'
    brw = start_browser(args.webdriver)
    brw.get(base_search_url)
    time.sleep(PAGELOAD_TO)

    input('[PLANNER] 请先登录 Cookidoo，然后回到终端按 Enter 继续…')

    # Iterate keywords
    for kw in keywords:
        try:
            urls = collect_urls_for_keyword(brw, base_search_url, kw, args.max_per_keyword)
            all_urls.update(urls)
            print(f"[PLANNER] keyword '{kw}' done → accumulated total: {len(all_urls)}\n")
        except Exception as exc:
            print(f"[PLANNER] !!! Keyword '{kw}' failed: {exc}")

    # Save to output JSON – list ensures deterministic order
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as fh:
        json.dump(sorted(all_urls), fh, ensure_ascii=False, indent=2)
    print(f"[PLANNER] Finished. {len(all_urls)} unique recipe URLs written to {args.output}")

    brw.quit()


if __name__ == '__main__':
    main() 