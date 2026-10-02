import json
import os
import re
import sys
import time
import urllib3
from bs4 import BeautifulSoup

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}


def parse_search_or_store_page(html):
    soup = BeautifulSoup(html, "html.parser")
    products = []
    seen_asins = set()

    # 1. Standard Amazon Search Result Cards
    for card in soup.select("div[data-asin]"):
        asin = card.get("data-asin", "").strip().upper()
        if not asin or len(asin) != 10 or asin in seen_asins:
            continue

        h2 = card.find("h2")
        title = h2.get_text(strip=True) if h2 else ""
        if not title:
            continue

        # Image
        img = card.select_one("img.s-image")
        image_url = img.get("src", "") if img else ""

        # Price
        price = None
        p_elem = card.select_one(".priceToPay span.a-price-whole") or card.select_one(".a-price .a-offscreen") or card.select_one("span.a-price-whole")
        if p_elem:
            clean = re.sub(r"[^\d]", "", p_elem.get_text(strip=True))
            if clean:
                val = int(clean)
                if val > 0:
                    price = val

        # Availability & Stock status
        card_text = card.get_text(separator=" ", strip=True)
        status = "on_sale"
        availability = "✅ In Stock"

        if "発売予定日" in card_text or "予約" in card_text:
            match = re.search(r"(\d+月\d+日)発売予定", card_text)
            date_str = f" ({match.group(1)})" if match else ""
            availability = f"📦 Pre-order{date_str}"
            status = "on_sale"
        elif "一時的に在庫切れ" in card_text or "Currently unavailable" in card_text or "在庫切れ" in card_text:
            availability = "❌ Out of Stock"
            status = "sold"
        elif "残り" in card_text and "点" in card_text:
            match = re.search(r"残り(\d+点)", card_text)
            qty_str = match.group(1) if match else "few"
            availability = f"⚠️ Only {qty_str} left"
            status = "on_sale"

        canonical_url = f"https://www.amazon.co.jp/dp/{asin}"

        products.append({
            "id": f"amz_{asin}",
            "title": title,
            "url": canonical_url,
            "image": image_url,
            "price": price,
            "status": status,
            "availability": availability,
            "condition": "🆕 Brand New (Amazon)",
            "shipping": "🚚 Prime / Amazon JP",
            "seller_id": "Amazon.co.jp",
            "is_auction": False,
            "category": "Amazon Beyblade X",
            "source": "amazon"
        })
        seen_asins.add(asin)

    return products


def fetch_amazon_search_query(url, label=""):
    try:
        from playwright.sync_api import sync_playwright
        print(f"[Amazon] Fetching store/search: {label or url}...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="ja-JP",
                extra_http_headers={"Accept-Language": "ja-JP,ja;q=0.9"}
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=35000)
            html = page.content()
            browser.close()
            items = parse_search_or_store_page(html)
            print(f"  [+] Discovered {len(items)} products from {label or url}")
            return items
    except Exception as e:
        print(f"  [!] Failed to fetch search/store {url}: {e}")
        return []


def fetch_amazon_listings(config_path="config.json"):
    if not os.path.exists(config_path):
        return []

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"[!] Error loading config in amazon_source: {e}")
        return []

    searches = cfg.get("amazon_searches", [])
    # Backward compatibility if watchlist is still used
    if not searches and cfg.get("amazon_watchlist"):
        searches = [{"url": entry.get("url") if isinstance(entry, dict) else str(entry), "label": entry.get("label", "") if isinstance(entry, dict) else ""} for entry in cfg.get("amazon_watchlist", [])]

    if not searches:
        return []

    print("\n" + "=" * 60)
    print(f"Checking {len(searches)} Amazon search/store queries...")
    print("=" * 60)

    seen_ids = set()
    all_items = []

    for entry in searches:
        if isinstance(entry, dict):
            url = entry.get("url", "")
            label = entry.get("label", "")
        else:
            url = str(entry)
            label = ""

        if not url:
            continue

        items = fetch_amazon_search_query(url, label=label)
        for it in items:
            if it["id"] not in seen_ids:
                seen_ids.add(it["id"])
                all_items.append(it)
        time.sleep(1)

    print(f"[+] Total unique Amazon products found: {len(all_items)}")
    print("=" * 60)
    return all_items


if __name__ == "__main__":
    items = fetch_amazon_listings()
    print(f"\nFetched {len(items)} items from Amazon.")
    for it in items[:10]:
        print(f"  [{it['id']}] {it['title'][:40]} | ¥{it['price']} | {it['availability']} | Status: {it['status']}")
