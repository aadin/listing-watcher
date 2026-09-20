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
    "Upgrade-Insecure-Requests": "1"
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
    # If already an ASIN (10 chars alphanumeric)
    if re.fullmatch(r"[A-Z0-9]{10}", url_or_id, re.IGNORECASE):
        return url_or_id.upper()
    match = ASIN_REGEX.search(url_or_id)
    if match:
        return match.group(1).upper()
    return None


def _parse_amazon_html(html, asin, original_url=""):
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # 1. Title
    title_elem = soup.find(id="productTitle")
    title = title_elem.get_text(strip=True) if title_elem else ""

    # Detect anti-bot/CAPTCHA
    if not title:
        page_title = soup.title.get_text(strip=True) if soup.title else ""
        if "captcha" in html.lower() or "robot check" in html.lower() or "bot check" in html.lower():
            print(f"  [!] Amazon CAPTCHA/bot check detected for ASIN {asin}")
            return None
        if "Amazon.co.jp" in page_title:
            title = page_title

    # 2. Image
    image_url = ""
    img_elem = soup.find(id="landingImage") or soup.select_one("#imgTagWrapperId img") or soup.select_one("#main-image")
    if img_elem:
        image_url = img_elem.get("data-old-hires") or img_elem.get("src") or ""

    # 3. Price
    price = None
    price_selectors = [
        ".priceToPay span.a-price-whole",
        ".a-price .a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "#corePrice_feature_div .a-offscreen",
        "#corePriceDisplay_desktop_feature_div .a-offscreen",
        "#apex_desktop .a-price .a-offscreen"
    ]
    for sel in price_selectors:
        for p_elem in soup.select(sel):
            price_text = p_elem.get_text(strip=True)
            clean_num = re.sub(r"[^\d]", "", price_text)
            if clean_num:
                price = int(clean_num)
                break
        if price is not None:
            break

    # If price not found in standard selectors, search for links targeting this ASIN
    if price is None:
        for a in soup.find_all("a", href=True):
            if asin in a["href"]:
                p_off = a.select_one(".a-price .a-offscreen")
                if p_off:
                    clean_num = re.sub(r"[^\d]", "", p_off.get_text(strip=True))
                    if clean_num:
                        price = int(clean_num)
                        break

    # 4. Availability & Status
    avail_elem = soup.find(id="availability")
    avail_text = avail_elem.get_text(strip=True) if avail_elem else ""

    is_out_of_stock = False
    for kw in OUT_OF_STOCK_KEYWORDS:
        if kw.lower() in avail_text.lower() or kw.lower() in html.lower():
            is_out_of_stock = True
            break

    status = "sold" if is_out_of_stock else "on_sale"
    if price is None and not is_out_of_stock:
        # Check if there are buying choices / other sellers
        if soup.find(id="buybox-see-all-buying-choices"):
            status = "on_sale"

    # 5. Seller & Shipping
    seller = "Amazon.co.jp"
    merchant_elem = soup.find(id="merchant-info")
    if merchant_elem:
        m_text = merchant_elem.get_text(strip=True)
        if m_text:
            seller = m_text[:50]

    canonical_url = f"https://www.amazon.co.jp/dp/{asin}"

    return {
        "id": f"amz_{asin}",
        "title": title or f"Amazon Product {asin}",
        "url": canonical_url,
        "image": image_url,
        "price": price or 0,
        "status": status,
        "condition": "🆕 Brand New (Amazon)",
        "shipping": "🚚 Prime / Amazon JP",
        "seller_id": seller,
        "is_auction": False,
        "category": "Amazon Tracked",
        "source": "amazon"
    }


def _fetch_via_requests(asin):
    url = f"https://www.amazon.co.jp/dp/{asin}"
    try:
        session = requests.Session()
        cookies = {"i18n-prefs": "JPY", "lc-acbjp": "ja_JP"}
        r = session.get(url, headers=HEADERS, cookies=cookies, verify=False, timeout=20)
        if r.status_code == 200:
            parsed = _parse_amazon_html(r.text, asin, url)
            if parsed and parsed.get("price", 0) > 0:
                return parsed
            # Also try offer listing URL if buybox has no price
            url_olp = f"https://www.amazon.co.jp/gp/offer-listing/{asin}"
            r_olp = session.get(url_olp, headers=HEADERS, cookies=cookies, verify=False, timeout=20)
            if r_olp.status_code == 200:
                parsed_olp = _parse_amazon_html(r_olp.text, asin, url)
                if parsed_olp and parsed_olp.get("price", 0) > 0:
                    if parsed and parsed.get("image"):
                        parsed_olp["image"] = parsed["image"]
                    return parsed_olp
                return parsed
    except Exception as e:
        print(f"  [!] Direct HTTP fetch error for {asin}: {e}")
    return None


def _fetch_via_playwright(asin):
    try:
        from playwright.sync_api import sync_playwright
        url = f"https://www.amazon.co.jp/dp/{asin}"
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="ja-JP",
                extra_http_headers={"Accept-Language": "ja-JP,ja;q=0.9"}
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            html = page.content()
            browser.close()
            return _parse_amazon_html(html, asin, url)
    except Exception as e:
        print(f"  [!] Playwright fetch error for {asin}: {e}")
        return None


def fetch_amazon_item(url_or_asin):
    asin = extract_asin(url_or_asin)
    if not asin:
        print(f"[!] Invalid Amazon URL/ASIN: {url_or_asin}")
        return None

    # Step 1: Try fast direct HTTP first
    item = _fetch_via_requests(asin)
    if item and item.get("price", 0) > 0:
        return item

    # Step 2: Fallback to Playwright if price missing or blocked
    print(f"  [*] Falling back to Playwright for ASIN {asin}...")
    item = _fetch_via_playwright(asin)
    return item


def fetch_amazon_listings(config_path="config.json"):
    if not os.path.exists(config_path):
        return []

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"[!] Error loading config in amazon_source: {e}")
        return []

    watchlist = cfg.get("amazon_watchlist", [])
    if not watchlist:
        return []

    print("\n" + "=" * 60)
    print(f"Checking {len(watchlist)} Amazon watchlist items...")
    print("=" * 60)

    results = []
    for entry in watchlist:
        if isinstance(entry, dict):
            url = entry.get("url", "")
            label = entry.get("label", "")
        else:
            url = str(entry)
            label = ""

        if not url:
            continue

        print(f"[Amazon] Checking {label or url}...")
        item = fetch_amazon_item(url)
        if item:
            print(f"  [+] Found: {item['title'][:50]} | ¥{item['price']:,} | Status: {item['status']}")
            results.append(item)
        else:
            print(f"  [-] Failed to fetch Amazon item for {url}")
        time.sleep(1)

    return results


if __name__ == "__main__":
    items = fetch_amazon_listings()
    print(f"\nFetched {len(items)} items from Amazon.")
    for it in items:
        print(it)
