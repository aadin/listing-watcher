import os
import json
import sys
import subprocess
import time

sys.stdout.reconfigure(encoding='utf-8')

# Auto-install missing packages on server
required_packages = ["requests", "mercapi", "beautifulsoup4", "deep-translator"]
for package in required_packages:
    try:
        __import__(package)
    except ImportError:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        except Exception:
            pass

from sources.mercari_source import fetch_listings, fetch_items_status
from notifiers.discord import notify

# Load config
with open("config.json", "r", encoding="utf-8") as f:
    cfg = json.load(f)

# Resolve webhooks config
webhooks_cfg = cfg.get("webhooks", {})
if not isinstance(webhooks_cfg, dict):
    webhooks_cfg = {"default": webhooks_cfg} if webhooks_cfg else {}

# Map environment variables to webhook config keys
env_vars = {
    "default": "DISCORD_WEBHOOK",
    "sold": "DISCORD_WEBHOOK_SOLD",
    "deals": "DISCORD_WEBHOOK_DEALS",
    "mid_range": "DISCORD_WEBHOOK_MID_RANGE",
    "premium": "DISCORD_WEBHOOK_PREMIUM"
}

for key, env_name in env_vars.items():
    env_val = os.getenv(env_name)
    if env_val:
        webhooks_cfg[key] = env_val

# Legacy fallback
if not webhooks_cfg.get("default"):
    webhooks_cfg["default"] = cfg.get("webhook")

# Load previously seen items and upgrade format if list
seen = {}
if os.path.exists("seen.json"):
    try:
        with open("seen.json", "r", encoding="utf-8") as f:
            raw_seen = json.load(f)
        if isinstance(raw_seen, list):
            # Upgrade old list to dictionary format
            seen = {item_id: {"status": "on_sale"} for item_id in raw_seen}
        elif isinstance(raw_seen, dict):
            seen = raw_seen
    except Exception as e:
        print(f"[!] Error loading seen.json, starting fresh: {e}")

changed = False
def enrich_item_metadata(target_dict, source_item, current_time):
    fields = ("condition", "shipping", "category", "image", "url", "seller_id", "title")
    updated = False
    for f in fields:
        if source_item.get(f) and not target_dict.get(f):
            target_dict[f] = source_item[f]
            updated = True
    if "price_history" not in target_dict and target_dict.get("price") is not None:
        target_dict["price_history"] = [{
            "price": target_dict["price"],
            "timestamp": target_dict.get("last_checked", current_time)
        }]
        updated = True
    return updated

price_tiers = cfg.get("price_tiers", {})

# 1. Fetch and process new listings
print("\nFetching new listings...")
new_items = fetch_listings()
current_time = int(time.time())

for item in new_items:
    item_id = item["id"]
    if item_id not in seen:
        seen[item_id] = {
            "status": "on_sale",
            "price": item["price"],
            "title": item["title"],
            "condition": item.get("condition", ""),
            "shipping": item.get("shipping", ""),
            "category": item.get("category", ""),
            "image": item.get("image", ""),
            "url": item.get("url", f"https://jp.mercari.com/item/{item_id}"),
            "seller_id": item.get("seller_id"),
            "price_history": [{"price": item["price"], "timestamp": current_time}],
            "last_checked": current_time
        }
        changed = True
        notify(webhooks_cfg, item, price_tiers=price_tiers)
    else:
        old_details = seen[item_id]
        if enrich_item_metadata(old_details, item, current_time):
            changed = True

        if old_details.get("status") == "on_sale":
            old_price = old_details.get("price")
            new_price = item.get("price")
            if old_price is not None and new_price is not None:
                if new_price < old_price:
                    print(f"[!] Price drop for item {item_id} (search): ¥{old_price} -> ¥{new_price} ({item['title']})")
                    item["old_price"] = old_price
                    notify(webhooks_cfg, item, price_tiers=price_tiers)
                    seen[item_id]["price"] = new_price
                    seen[item_id]["last_checked"] = current_time
                    seen[item_id].setdefault("price_history", []).append({"price": new_price, "timestamp": current_time})
                    changed = True
                elif new_price > old_price:
                    seen[item_id]["price"] = new_price
                    seen[item_id]["last_checked"] = current_time
                    seen[item_id].setdefault("price_history", []).append({"price": new_price, "timestamp": current_time})
                    changed = True

# 2. Check previously active items for sold status
active_items = [(item_id, details) for item_id, details in seen.items() if details.get("status") == "on_sale"]
# Sort active items by their last_checked timestamp (oldest/missing first) to check in round-robin fashion
active_items.sort(key=lambda x: x[1].get("last_checked", 0))
active_ids_to_check = [item_id for item_id, _ in active_items[:300]]

if active_ids_to_check:
    print(f"\nChecking status of {len(active_ids_to_check)} active items...")
    current_time = int(time.time())

    status_updates = fetch_items_status(active_ids_to_check)
    for updated_item in status_updates:
        item_id = updated_item["id"]
        old_details = seen.get(item_id, {})
        if item_id not in seen:
            continue

        # Skip items that failed to fetch so they get retried in future runs
        if updated_item.get("status") == "error":
            continue

        # Mark item as checked now that we got a valid response
        seen[item_id]["last_checked"] = current_time
        if enrich_item_metadata(seen[item_id], updated_item, current_time):
            changed = True

        if updated_item["status"] == "sold" and old_details.get("status") == "on_sale":
            print(f"[!] Item {item_id} sold: {updated_item['title']}")
            notify(webhooks_cfg, updated_item, price_tiers=price_tiers)
            seen[item_id]["status"] = "sold"
            changed = True
        elif updated_item["status"] == "removed" and old_details.get("status") == "on_sale":
            print(f"[#] Item {item_id} was removed/deleted.")
            seen[item_id]["status"] = "removed"
            changed = True
        elif updated_item["status"] == "on_sale" and old_details.get("status") == "on_sale":
            old_price = old_details.get("price")
            new_price = updated_item.get("price")
            if old_price is not None and new_price is not None:
                if new_price < old_price:
                    print(f"[!] Price drop for item {item_id}: ¥{old_price} -> ¥{new_price} ({updated_item['title']})")
                    updated_item["old_price"] = old_price
                    notify(webhooks_cfg, updated_item, price_tiers=price_tiers)
                    seen[item_id]["price"] = new_price
                    seen[item_id].setdefault("price_history", []).append({"price": new_price, "timestamp": current_time})
                    changed = True
                elif new_price > old_price:
                    print(f"[#] Price increased for item {item_id}: ¥{old_price} -> ¥{new_price} ({updated_item['title']})")
                    seen[item_id]["price"] = new_price
                    seen[item_id].setdefault("price_history", []).append({"price": new_price, "timestamp": current_time})
                    changed = True

# 3. Prune old sold/removed entries older than 7 days
seven_days_ago = int(time.time()) - (7 * 86400)
to_prune = [
    item_id for item_id, details in seen.items()
    if details.get("status") in ("sold", "removed") and details.get("last_checked", 0) < seven_days_ago
]
if to_prune:
    print(f"\nPruning {len(to_prune)} old sold/removed items (>7 days old)...")
    for item_id in to_prune:
        del seen[item_id]
    changed = True

# Save updated seen state
if changed:
    with open("seen.json", "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)

print("\nDone")