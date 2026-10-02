import json
import os
import re
import sys
import time
import urllib3
from bs4 import BeautifulSoup
import requests

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
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1"
}

ASIN_REGEX = re.compile(r"(?:/dp/|/gp/product/|/d/|/asin/)([A-Z0-9]{10})", re.IGNORECASE)

OUT_OF_STOCK_KEYWORDS = [
    "currently unavailable",
    "一時的に在庫切れ",
    "在庫切れ",
    "この商品は現在お取り扱いできません",
    "お取り扱いできません"
]


def extract_asin(url_or_id):
    if not url_or_id:
        return None
    if re.fullmatch(r"[A-Z0-9]{10}", url_or_id, re.IGNORECASE):
        return url_or_id.upper()
    match = ASIN_REGEX.search(url_or_id)
    if match:
        return match.group(1).upper()
    return None


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
    except ImportError:
        print("  [!] Playwright not installed. Skipping Amazon search fetch.")
        return []

    print(f"[Amazon] Fetching store/search: {label or url}...")

    for attempt in range(1, 3):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-infobars",
                        "--ignore-certificate-errors"
                    ]
                )
                context = browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    locale="ja-JP",
                    viewport={"width": 1920, "height": 1080},
                    extra_http_headers={
                        "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
                        "sec-ch-ua": HEADERS["sec-ch-ua"],
                        "sec-ch-ua-mobile": "?0",
                        "sec-ch-ua-platform": '"Windows"',
                        "upgrade-insecure-requests": "1"
                    }
                )
                context.add_cookies([
                    {"name": "i18n-prefs", "value": "JPY", "domain": ".amazon.co.jp", "path": "/"},
                    {"name": "lc-acbjp", "value": "ja_JP", "domain": ".amazon.co.jp", "path": "/"},
                    {"name": "sp-cdn", "value": "L5Z9:JP", "domain": ".amazon.co.jp", "path": "/"}
                ])
                page = context.new_page()
                page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

                page.goto(url, wait_until="domcontentloaded", timeout=40000)

                try:
                    page.wait_for_selector("div[data-asin]", timeout=12000)
                except Exception:
                    pass

                html = page.content()
                browser.close()

                items = parse_search_or_store_page(html)
                if items:
                    print(f"  [+] Discovered {len(items)} products from {label or url}")
                    return items
                else:
                    if "captcha" in html.lower() or "robot check" in html.lower():
                        print(f"  [!] Amazon CAPTCHA encountered on attempt {attempt}.")
                    if attempt < 2:
                        print("  [*] Retrying with backoff...")
                        time.sleep(3)
        except Exception as e:
            print(f"  [!] Attempt {attempt} error for {url}: {e}")
            if attempt < 2:
                time.sleep(3)

    print(f"  [-] Failed to extract products from {url}")
    return []


def _parse_single_product_html(html, asin):
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")

    title_elem = soup.find(id="productTitle")
    title = title_elem.get_text(strip=True) if title_elem else ""
    if not title:
        return None

    img_elem = soup.find(id="landingImage") or soup.select_one("#imgTagWrapperId img") or soup.select_one("#main-image")
    image_url = img_elem.get("data-old-hires") or img_elem.get("src") or "" if img_elem else ""

    avail_elem = soup.find(id="availability")
    avail_text = avail_elem.get_text(strip=True) if avail_elem else ""

    is_out_of_stock = False
    for kw in OUT_OF_STOCK_KEYWORDS:
        if kw.lower() in avail_text.lower() or kw.lower() in html.lower():
            is_out_of_stock = True
            break

    status = "sold" if is_out_of_stock else "on_sale"
    availability = "❌ Out of Stock" if is_out_of_stock else "✅ In Stock"
    if "発売予定日" in avail_text or "予約" in avail_text:
        match = re.search(r"(\d+月\d+日)発売予定", avail_text)
        date_str = f" ({match.group(1)})" if match else ""
        availability = f"📦 Pre-order{date_str}"
    elif "残り" in avail_text:
        match = re.search(r"残り(\d+点)", avail_text)
        qty_str = match.group(1) if match else "few"
        availability = f"⚠️ Only {qty_str} left"

    price = None
    main_containers = [
        soup.find(id="corePriceDisplay_desktop_feature_div"),
        soup.find(id="corePrice_feature_div"),
        soup.find(id="apex_desktop"),
        soup.find(id="desktop_buybox"),
        soup.find(id="buybox"),
        soup.find(id="centerCol")
    ]
    price_selectors = [
        ".priceToPay span.a-price-whole",
        ".priceToPay .a-offscreen",
        ".a-price.apexPriceToPay .a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        ".a-price .a-offscreen",
        "span.a-price-whole",
        "#olp-upd-new .a-price .a-offscreen",
        "#buybox-see-all-buying-choices a"
    ]
    for container in main_containers:
        if not container:
            continue
        for bad in container.select(".a-carousel, [id*='sp_detail'], [id*='similarities'], [id*='recs'], .sp_offerVertical, .tabular-buybox"):
            bad.decompose()
        for sel in price_selectors:
            for p_elem in container.select(sel):
                price_text = p_elem.get_text(strip=True)
                clean_num = re.sub(r"[^\d]", "", price_text)
                if clean_num:
                    val = int(clean_num)
                    if val > 0:
                        price = val
                        break
            if price is not None:
                break
        if price is not None:
            break

    seller = "Amazon.co.jp"
    merchant_elem = soup.find(id="merchant-info")
    if merchant_elem:
        m_text = merchant_elem.get_text(strip=True)
        if m_text:
            seller = m_text[:50]

    return {
        "id": f"amz_{asin}",
        "title": title,
        "url": f"https://www.amazon.co.jp/dp/{asin}",
        "image": image_url,
        "price": price,
        "status": status,
        "availability": availability,
        "condition": "🆕 Brand New (Amazon)",
        "shipping": "🚚 Prime / Amazon JP",
        "seller_id": seller,
        "is_auction": False,
        "category": "Amazon Beyblade X",
        "source": "amazon"
    }


def fetch_single_amazon_product(url_or_asin):
    asin = extract_asin(url_or_asin)
    if not asin:
        return None
    url = f"https://www.amazon.co.jp/dp/{asin}"
    try:
        session = requests.Session()
        cookies = {"i18n-prefs": "JPY", "lc-acbjp": "ja_JP", "sp-cdn": "L5Z9:JP"}
        r = session.get(url, headers=HEADERS, cookies=cookies, verify=False, timeout=20)
        if r.status_code == 200:
            parsed = _parse_single_product_html(r.text, asin)
            if parsed and parsed.get("title"):
                return parsed
    except Exception:
        pass
    return None


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
    watchlist = cfg.get("amazon_watchlist", [])

    if not searches and not watchlist:
        return []

    print("\n" + "=" * 60)
    print(f"Checking Amazon queries (searches: {len(searches)}, watchlist: {len(watchlist)})...")
    print("=" * 60)

    seen_ids = set()
    all_items = []

    # 1. Process store / search queries
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

    # 2. Process individual watchlist items (if any)
    for entry in watchlist:
        if isinstance(entry, dict):
            url = entry.get("url", "")
            label = entry.get("label", "")
        else:
            url = str(entry)
            label = ""

        asin = extract_asin(url)
        if not asin or f"amz_{asin}" in seen_ids:
            continue

        item = fetch_single_amazon_product(url)
        if item:
            seen_ids.add(item["id"])
            all_items.append(item)

    print(f"[+] Total unique Amazon products found: {len(all_items)}")
    print("=" * 60)
    return all_items


if __name__ == "__main__":
    items = fetch_amazon_listings()
    print(f"\nFetched {len(items)} items from Amazon.")
    for it in items[:10]:
        print(f"  [{it['id']}] {it['title'][:40]} | ¥{it['price']} | {it['availability']} | Status: {it['status']}")
