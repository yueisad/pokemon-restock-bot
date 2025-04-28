import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

STATE_FILE = 'state.json'
DISCORD_WEBHOOK = None

def load_state():

    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
                # Add backward compatibility: if a product entry doesn't have
                # 'notified_for_available', add it and set to False.
                if 'products' in state and isinstance(state['products'], dict):
                    for handle, p_state in state['products'].items():
                        if isinstance(p_state, dict) and 'notified_for_available' not in p_state:
                            p_state['notified_for_available'] = False
                return state
        except json.JSONDecodeError:
            print(f"Warning: Could not decode JSON from {STATE_FILE}. Starting with empty state.")
            return {'products': {}}
    return {'products': {}}  

def save_state(state):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"Error saving state to {STATE_FILE}: {e}")


def fetch_all_products(url):
    try:
        resp = requests.get(f"{url.rstrip('/')}/products.json?limit=250", timeout=15) # Increased timeout slightly
        resp.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        return resp.json().get('products', [])
    except requests.exceptions.RequestException as e:
        print(f"Error fetching products from {url}: {e}")
        return None # Return None to indicate failure

def chunk_text_by_lines(text, limit=2000):
    lines = text.splitlines(keepends=True)
    chunks, cur = [], ""
    for line in lines:
        if len(cur) + len(line) > limit:
            chunks.append(cur.strip()); cur = "" # Use strip to remove trailing newline if it caused chunking
        cur += line
    if cur: chunks.append(cur.strip())
    return chunks

def notify_discord(message):
    if not DISCORD_WEBHOOK:
        print("Discord webhook not configured.")
        return

    chunks = chunk_text_by_lines(message)
    for idx, chunk in enumerate(chunks, start=1):
        print(f"Sending chunk {idx}/{len(chunks)}...")
        try:
            resp = requests.post(DISCORD_WEBHOOK, json={'content': chunk}, timeout=10) # Added timeout
            resp.raise_for_status()
            print(f"→ Sent chunk {idx}/{len(chunks)}")
        except requests.exceptions.RequestException as e:
            print(f"Error sending Discord webhook message chunk {idx}/{len(chunks)}: {e}")
            break


def main():
    global DISCORD_WEBHOOK
    load_dotenv()
    DISCORD_WEBHOOK = os.getenv('DISCORD_WEBHOOK')
    urls = [u.strip() for u in os.getenv('COLLECTION_URLS', '').split(',') if u.strip()]
    if not DISCORD_WEBHOOK or not urls:
        print("❌ Define DISCORD_WEBHOOK and COLLECTION_URLS in .env"); return

    state = load_state()
    # Use .get with a default empty dict for safety if state file is corrupted initially
    old_products_state = state.get('products', {})
    new_state = {'products': {}}
    new_items_to_notify, restocked_to_notify = [], []

    # Keep track of handles processed in this run to identify removed items if needed later
    processed_handles = set()

    for url in urls:
        print(f"Checking {url}…")
        products = fetch_all_products(url)

        if products is None: # Skip this URL if fetching failed
             continue


        for p in products:
            handle = p['handle']
            title  = p['title']
            current_avail  = any(v.get('available') for v in p.get('variants', []))

            # Add handle to processed set
            processed_handles.add(handle)

            # Get the previous state for this product
            old_p_state = old_products_state.get(handle)

            # Determine previous availability and notification status, defaulting to False
            old_avail = old_p_state.get('available', False) if old_p_state else False
            old_notified_for_available = old_p_state.get('notified_for_available', False) if old_p_state else False

            # Initialize the new state for this product, inheriting old notification status
            new_p_state = {
                'title': title,
                'available': current_avail,
                'notified_for_available': old_notified_for_available # Start with the old notification status
            }

            is_new_item = handle not in old_products_state
            is_restock_transition = not old_avail and current_avail # Was unavailable, now available

            should_notify_this_product = False

            if is_new_item and current_avail:

                 if not new_p_state['notified_for_available']:
                    new_items_to_notify.append((title, f"{url}/products/{handle}"))
                    should_notify_this_product = True

            elif is_restock_transition:
    
                if not new_p_state['notified_for_available']:
                    restocked_to_notify.append((title, f"{url}/products/{handle}"))
                    should_notify_this_product = True

            if current_avail and should_notify_this_product:

                 new_p_state['notified_for_available'] = True
            elif not current_avail:

                new_p_state['notified_for_available'] = False

            new_state['products'][handle] = new_p_state

    for handle, old_p_state in old_products_state.items():
        if handle not in processed_handles:
            print(f"Product '{old_p_state.get('title', handle)}' ({handle}) not found in current fetch.")

            carried_over_state = {
                 'title': old_p_state.get('title', handle),
                 'available': False, # Assume unavailable if not found
                 'notified_for_available': False # Reset flag so a notification is sent if it reappears
            }
            new_state['products'][handle] = carried_over_state

    save_state(new_state)
    print("State saved.")

    if not new_items_to_notify and not restocked_to_notify:
        print("No new products or restocks to notify about.")
    else:
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        parts = [f"🚨 **Stock Alert** 🚨\nChecked at: {ts}\n"]
        if new_items_to_notify:
            parts.append("**🆕 New products:**")
            parts += [f"- {t} (<{link}>)" for t, link in new_items_to_notify]
        if restocked_to_notify:
            parts.append("\n**🔄 Restocked:**")
            parts += [f"- {t} (<{link}>)" for t, link in restocked_to_notify]

        message = "\n".join(parts)
        notify_discord(message)

if __name__ == "__main__":
    main()