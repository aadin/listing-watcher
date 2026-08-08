import requests
from deep_translator import GoogleTranslator


def translate_title(text):
    try:
        return GoogleTranslator(source="ja", target="en").translate(text)
    except Exception as e:
        print(f"[!] Translation failed: {e}")
        return None


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
    else:
        if price <= deals_limit:
            embed_color = 3066993  # 0x2ECC71 (Green)
        elif price >= premium_start:
            embed_color = 10181046  # 0x9B59B6 (Purple)
        else:
            embed_color = 3447003  # 0x3498DB (Blue)

    fields = [{"name": "Price", "value": f"¥{price:,}", "inline": True}]
    
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