from pathlib import Path

import requests

if __name__ == "__main__":
    url = input("Enter URL: ").strip()

    response = requests.get(
        url,
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,*/*",
        },
    )

    print()
    print("STATUS:", response.status_code)
    print("URL:", response.url)
    print("CONTENT TYPE:", response.headers.get("Content-Type"))
    print("CONTENT LENGTH:", len(response.content))

    print()
    print("HEADERS:")
    for key, value in response.headers.items():
        print(f"{key}: {value}")

    print()
    print("BODY:")
    print(response.text[:5000])

    Path("data/source/debug_response.html").write_text(
        response.text,
        encoding="utf-8",
    )

    print()
    print("Saved debug response to:")
    print("data/source/debug_response.html")
