import requests
from bs4 import BeautifulSoup

SEARCH_URL = "https://jp.mercari.com/en/search?keyword=%E3%83%A1%E3%82%BF%E3%83%AB%E3%83%95%E3%82%A1%E3%82%A4%E3%83%88%E3%83%99%E3%82%A4%E3%83%96%E3%83%AC%E3%83%BC%E3%83%89&status=on_sale&sort=created_time&order=desc"

HEADERS = {
    "User-Agent": "listing-watcher/1.0"
}


def fetch_listings():
    print("=" * 60)
    print("Starting fetch...")
    print(f"URL: {SEARCH_URL}")
    print("=" * 60)

    try:
        response = requests.get(
            SEARCH_URL,
            headers=HEADERS,
            timeout=20,
        )

        print(f"[+] Status Code : {response.status_code}")
        print(f"[+] Content-Type: {response.headers.get('Content-Type')}")
        print(f"[+] HTML Size   : {len(response.text)} bytes")

        response.raise_for_status()

    except requests.RequestException as e:
        print(f"[!] Request failed: {e}")
        return []

    with open("debug.html", "w", encoding="utf-8") as f:
        f.write(response.text)

    print("[+] Saved response to debug.html")

    soup = BeautifulSoup(response.text, "html.parser")

    print("\n===== Debug Information =====")
    print(f"Title       : {soup.title.string if soup.title else 'None'}")
    print(f"Links       : {len(soup.find_all('a'))}")
    print(f"Images      : {len(soup.find_all('img'))}")
    print(f"Forms       : {len(soup.find_all('form'))}")
    print(f"Scripts     : {len(soup.find_all('script'))}")
    print(f"Stylesheets : {len(soup.find_all('link'))}")
    print("=============================")

    return []


if __name__ == "__main__":
    fetch_listings()