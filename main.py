import os
import json
import sys
import subprocess

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
            "title": item["title"]
        }
        changed = True
        notify(webhooks_cfg, item, price_tiers=price_tiers)

# 2. Check previously active items for sold status
active_ids = [item_id for item_id, details in seen.items() if details.get("status") == "on_sale"]
# Limit checks to the 100 most recent active listings to optimize performance
active_ids_to_check = active_ids[-100:]

if active_ids_to_check:
    print(f"\nChecking status of {len(active_ids_to_check)} active items...")
    status_updates = fetch_items_status(active_ids_to_check)
    for updated_item in status_updates:
        item_id = updated_item["id"]
        old_details = seen.get(item_id, {})
        if updated_item["status"] == "sold" and old_details.get("status") == "on_sale":
            print(f"[!] Item {item_id} sold: {updated_item['title']}")
            notify(webhooks_cfg, updated_item, price_tiers=price_tiers)
            seen[item_id]["status"] = "sold"
            changed = True

# Save updated seen state
if changed:
    with open("seen.json", "w") as f:
        json.dump(seen, f, indent=2)

print("\nDone")