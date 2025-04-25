import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

STATE_FILE = 'state.json'
DISCORD_WEBHOOK = None

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'products': {}}  # handle → {'title':…, 'available':…}

def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def fetch_all_products(url):
    resp = requests.get(f"{url.rstrip('/')}/products.json?limit=250", timeout=10)
    resp.raise_for_status()
    return resp.json().get('products', [])

def chunk_text_by_lines(text, limit=2000):
    lines = text.splitlines(keepends=True)
    chunks, cur = [], ""
    for line in lines:
        if len(cur) + len(line) > limit:
            chunks.append(cur); cur = ""
        cur += line
    if cur: chunks.append(cur)
    return chunks

def notify_discord(message):
    for idx, chunk in enumerate(chunk_text_by_lines(message), start=1):
        resp = requests.post(DISCORD_WEBHOOK, json={'content': chunk})
        resp.raise_for_status()
        print(f"→ Sent chunk {idx}/{len(chunk_text_by_lines(message))}")

def main():
    global DISCORD_WEBHOOK
    load_dotenv()
    DISCORD_WEBHOOK = os.getenv('DISCORD_WEBHOOK')
    urls = [u.strip() for u in os.getenv('COLLECTION_URLS', '').split(',') if u.strip()]
    if not DISCORD_WEBHOOK or not urls:
        print("❌ Define DISCORD_WEBHOOK and COLLECTION_URLS in .env"); return

    state = load_state()
    old = state['products']
    new_state = {'products': {}}
    new_items, restocked = [], []

    for url in urls:
        print(f"Checking {url}…")
        products = fetch_all_products(url)
        for p in products:
            handle = p['handle']
            title  = p['title']
            avail  = any(v.get('available') for v in p.get('variants', []))
            new_state['products'][handle] = {'title': title, 'available': avail}

            if handle not in old:
                new_items.append((title, f"{url}/products/{handle}"))
            elif not old[handle]['available'] and avail:
                restocked.append((title, f"{url}/products/{handle}"))

    # only notify if there’s something new or restocked
    if not new_items and not restocked:
        print("No new products or restocks.")
    else:
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        parts = [f"🚨 **Restock/New-product Alert** 🚨\nChecked at: {ts}\n"]
        if new_items:
            parts.append("**🆕 New products:**")
            parts += [f"- {t} ({link})" for t, link in new_items]
        if restocked:
            parts.append("\n**🔄 Restocked:**")
            parts += [f"- {t} ({link})" for t, link in restocked]

        notify_discord("\n".join(parts))
        save_state(new_state)

if __name__ == "__main__":
    main()
