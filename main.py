import os
import json
import sys
import subprocess
import time

# Auto-install missing packages on server
required_packages = ["requests", "mercapi", "beautifulsoup4", "deep-translator"]
for package in required_packages:
    try:
        __import__(package)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", package])

from sources.mercari_source import fetch_listings, fetch_items_status
from notifiers.discord import notify

# Load config
with open("config.json", "r") as f:
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
        with open("seen.json", "r") as f:
            raw_seen = json.load(f)
        if isinstance(raw_seen, list):
            # Upgrade old list to dictionary format
            seen = {item_id: {"status": "on_sale"} for item_id in raw_seen}
        elif isinstance(raw_seen, dict):
            seen = raw_seen
    except Exception as e:
        print(f"[!] Error loading seen.json, starting fresh: {e}")

changed = False
price_tiers = cfg.get("price_tiers", {})

# 1. Fetch and process new listings
print("\nFetching new listings...")
new_items = fetch_listings()
for item in new_items:
    item_id = item["id"]
    if item_id not in seen:
        seen[item_id] = {
            "status": "on_sale",
            "price": item["price"],
            "title": item["title"],
            "last_checked": int(time.time())
        }
        changed = True
        notify(webhooks_cfg, item, price_tiers=price_tiers)
    else:
        old_details = seen[item_id]
        if old_details.get("status") == "on_sale":
            old_price = old_details.get("price")
            new_price = item.get("price")
            if old_price is not None and new_price is not None:
                if new_price < old_price:
                    print(f"[!] Price drop for item {item_id} (search): ¥{old_price} -> ¥{new_price} ({item['title']})")
                    item["old_price"] = old_price
                    notify(webhooks_cfg, item, price_tiers=price_tiers)
                    seen[item_id]["price"] = new_price
                    seen[item_id]["last_checked"] = int(time.time())
                    changed = True
                elif new_price > old_price:
                    seen[item_id]["price"] = new_price
                    seen[item_id]["last_checked"] = int(time.time())
                    changed = True
            elif new_price is not None:
                seen[item_id]["price"] = new_price
                seen[item_id]["last_checked"] = int(time.time())
                changed = True

# 2. Check previously active items for sold status
active_items = [(item_id, details) for item_id, details in seen.items() if details.get("status") == "on_sale"]
# Sort active items by their last_checked timestamp (oldest/missing first) to check in round-robin fashion
active_items.sort(key=lambda x: x[1].get("last_checked", 0))
active_ids_to_check = [item_id for item_id, _ in active_items[:100]]

if active_ids_to_check:
    print(f"\nChecking status of {len(active_ids_to_check)} active items...")
    
    # Mark them as checked at current time to push them to the back of the queue
    current_time = int(time.time())
    for item_id in active_ids_to_check:
        seen[item_id]["last_checked"] = current_time
    changed = True

    status_updates = fetch_items_status(active_ids_to_check)
    for updated_item in status_updates:
        item_id = updated_item["id"]
        old_details = seen.get(item_id, {})
        # Safety check: only update if item is still in seen
        if item_id not in seen:
            continue
            
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
                    changed = True
                elif new_price > old_price:
                    print(f"[#] Price increased for item {item_id}: ¥{old_price} -> ¥{new_price} ({updated_item['title']})")
                    seen[item_id]["price"] = new_price
                    changed = True
            elif new_price is not None:
                seen[item_id]["price"] = new_price
                changed = True

# Save updated seen state
if changed:
    with open("seen.json", "w") as f:
        json.dump(seen, f, indent=2)

print("\nDone")