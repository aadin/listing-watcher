import requests
import urllib3
from deep_translator import GoogleTranslator, MyMemoryTranslator

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Monkeypatch requests Session.request to bypass SSL verification for translation calls
_orig_session_request = requests.Session.request

def _ssl_fallback_request(self, method, url, **kwargs):
    if "verify" not in kwargs:
        kwargs["verify"] = False
    return _orig_session_request(self, method, url, **kwargs)

_translation_cache = {}

def translate_title(text):
    if not text or not text.strip():
        return None

    text = text.strip()
    if text in _translation_cache:
        return _translation_cache[text]

    requests.Session.request = _ssl_fallback_request
    translated = None

    # 1. Primary: GoogleTranslator
    try:
        translated = GoogleTranslator(source="ja", target="en").translate(text)
    except Exception as e:
        pass

    # 2. Fallback: MyMemoryTranslator
    if not translated or translated.strip().lower() == text.lower():
        try:
            translated = MyMemoryTranslator(source="ja-JP", target="en-US").translate(text)
        except Exception as e:
            pass

    requests.Session.request = _orig_session_request

    if translated and translated.strip():
        _translation_cache[text] = translated.strip()
        return translated.strip()

    return None


# Cache the exchange rate to avoid making API requests for every single item in a run
_jpy_to_inr_rate_cache = None

def get_jpy_to_inr_rate():
    global _jpy_to_inr_rate_cache
    if _jpy_to_inr_rate_cache is not None:
        return _jpy_to_inr_rate_cache
    try:
        r = requests.get("https://open.er-api.com/v6/latest/JPY", timeout=5)
        if r.status_code == 200:
            data = r.json()
            rate = data["rates"]["INR"]
            _jpy_to_inr_rate_cache = rate
            return rate
    except Exception as e:
        print(f"[!] Failed to fetch JPY to INR exchange rate: {e}")
    return 0.55  # Fallback exchange rate


def notify(webhook_config, item, price_tiers=None):
    # 1. Resolve target webhook
    webhook_url = None
    
    # Defaults for price tiers
    deals_limit = 3000
    premium_start = 10000
    if price_tiers:
        deals_limit = price_tiers.get("deals_limit", 3000)
        premium_start = price_tiers.get("premium_start", 10000)

    status = item.get("status", "on_sale")
    price = item.get("price", 0)
    old_price = item.get("old_price")
    category = item.get("category", "Individual Bey")
    condition = item.get("condition", "")
    shipping = item.get("shipping", "")

    if isinstance(webhook_config, dict):
        if status == "sold":
            webhook_url = webhook_config.get("sold") or webhook_config.get("default")
        else:
            if price <= deals_limit:
                webhook_url = webhook_config.get("deals")
            elif price >= premium_start:
                webhook_url = webhook_config.get("premium")
            else:
                webhook_url = webhook_config.get("mid_range")
            
            # Fall back to default
            if not webhook_url:
                webhook_url = webhook_config.get("default")
    else:
        # It's a single string (legacy)
        webhook_url = webhook_config

    if not webhook_url or webhook_url.startswith("YOUR_DISCORD_WEBHOOK"):
        print(f"[!] No valid webhook URL configured for status={status}, price={price}. Skipping.")
        return

    # 2. Build rich embed
    original_title = item["title"]
    translated_title = translate_title(original_title)
    
    display_title = translated_title or original_title
    if status == "sold":
        display_title = f"🔴 SOLD: {display_title}"
        embed_color = 15158332  # 0xE74C3C (Red)
    elif old_price is not None:
        display_title = f"📉 PRICE DROP: {display_title}"
        embed_color = 15105570  # 0xE67E22 (Orange)
    else:
        if price <= deals_limit:
            embed_color = 3066993  # 0x2ECC71 (Green)
        elif price >= premium_start:
            embed_color = 10181046  # 0x9B59B6 (Purple)
        else:
            embed_color = 3447003  # 0x3498DB (Blue)

    inr_rate = get_jpy_to_inr_rate()
    inr_price = int(price * inr_rate)
    
    if old_price is not None:
        old_inr_price = int(old_price * inr_rate)
        drop_percent = int((old_price - price) / old_price * 100)
        price_value = (
            f"~~¥{old_price:,}~~ ➡️ **¥{price:,}** (-{drop_percent}%)\n"
            f"~~₹{old_inr_price:,}~~ ➡️ **₹{inr_price:,}**"
        )
        fields = [{"name": "Price Drop", "value": price_value, "inline": True}]
    else:
        fields = [{"name": "Price", "value": f"¥{price:,} (~₹{inr_price:,})", "inline": True}]
    
    if condition:
        fields.append({"name": "Condition", "value": condition, "inline": True})
    if shipping:
        fields.append({"name": "Shipping", "value": shipping, "inline": True})
    if category:
        fields.append({"name": "Category", "value": category, "inline": True})
        
    if translated_title and translated_title.strip().lower() != original_title.strip().lower():
        fields.append({"name": "Original Title (JP)", "value": original_title, "inline": False})

    payload = {
        "embeds": [{
            "title": display_title,
            "url": item["url"],
            "color": embed_color,
            "image": {"url": item["image"]} if item.get("image") else None,
            "fields": fields,
            "footer": {
                "text": f"ID: {item['id']}"
            }
        }]
    }

    try:
        r = requests.post(webhook_url, json=payload, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"[!] Failed to send Discord notification to {webhook_url}: {e}")