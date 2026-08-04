import requests
from deep_translator import GoogleTranslator


def translate_title(text):
    try:
        return GoogleTranslator(source="ja", target="en").translate(text)
    except Exception as e:
        print(f"[!] Translation failed: {e}")
        return None


def notify(webhook, item):
    original_title = item["title"]
    translated_title = translate_title(original_title)

    fields = [{"name": "Price", "value": f"¥{item['price']}"}]
    if translated_title and translated_title.strip().lower() != original_title.strip().lower():
        fields.append({"name": "Original (JP)", "value": original_title})

    payload = {"embeds": [{
        "title": translated_title or original_title,
        "url": item["url"],
        "image": {"url": item["image"]},
        "fields": fields
    }]}
    requests.post(webhook, json=payload, timeout=20)