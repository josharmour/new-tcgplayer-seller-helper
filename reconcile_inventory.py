import csv
import time
import logging
import datetime
import requests
import json
import os
import argparse
from playwright.sync_api import sync_playwright

# Configuration
OUTPUT_DIR = "output"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

CACHE_FILE = "tcg_id_cache.json"
LOG_FILE = os.path.join(OUTPUT_DIR, f"reconcile_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f)

try:
    from config import POKEMON_API_KEY
except ImportError:
    POKEMON_API_KEY = ""
    logging.warning("No config.py found. Pokemon API features may be limited.")

def get_tcgplayer_id_from_scryfall(scryfall_id, cache):
    if scryfall_id in cache:
        return cache[scryfall_id]
    
    url = f"https://api.scryfall.com/cards/{scryfall_id}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            tcg_id = data.get('tcgplayer_id')
            if tcg_id:
                cache[scryfall_id] = str(tcg_id)
                return str(tcg_id)
    except Exception as e:
        logging.error(f"Scryfall API error: {e}")
    return None

def get_tcgplayer_id_from_pokemon(name, cache):
    """Resolves TCGPlayer ID via Pokemon TCG API."""
    # Check cache first (using name as key for simplicity, though risky if duplicates)
    cache_key = f"POKEMON_{name}"
    if cache_key in cache:
        return cache[cache_key]

    api_url = "https://api.pokemontcg.io/v2/cards"
    headers = {"X-Api-Key": POKEMON_API_KEY}
    params = {"q": f"name:\"{name}\""}
    
    try:
        logging.info(f"  Querying Pokemon API for '{name}'...")
        response = requests.get(api_url, params=params, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if "data" in data and len(data["data"]) > 0:
                # Iterate to find one with a TCGPlayer URL
                for card in data["data"]:
                    if "tcgplayer" in card and "url" in card["tcgplayer"]:
                        url = card["tcgplayer"]["url"]
                        # Extract ID: https://prices.pokemontcg.io/tcgplayer/42382
                        import re
                        match = re.search(r"tcgplayer/(\d+)", url)
                        if match:
                            pid = match.group(1)
                            cache[cache_key] = pid
                            return pid
    except Exception as e:
        logging.error(f"Pokemon API error: {e}")
    return None

def search_product_id(page, name):
    """Searches for a product by name on the Admin portal and returns its ID."""
    try:
        logging.info(f"  Searching for ID: '{name}'...")
        # Navigate to Catalog Search
        page.goto("https://store.tcgplayer.com/admin/product/catalog")
        
        # Type name in search box
        page.fill("input#ProductName", name)
        page.click("input#searchButton")
        page.wait_for_load_state('domcontentloaded')
        
        # Look for first result link: /admin/product/manage/{id}
        # The table usually has a "Manage" link or the Name links to it.
        # Selector for the "Product Name" link in the results table
        link = page.locator("table.sTable tbody tr td a").first
        href = link.get_attribute("href")
        
        if href and "manage/" in href:
            # Extract ID from /admin/product/manage/123456
            return href.split("/")[-1]
    except Exception as e:
        logging.error(f"  Search failed: {e}")
    return None

def main():
    parser = argparse.ArgumentParser(description="Reconcile TCGPlayer Inventory from Master CSV")
    parser.add_argument("csv_file", help="Path to the Master CSV file")
    parser.add_argument("--live", action="store_true", help="Actually update inventory (disable dry run)")
    args = parser.parse_args()
    
    DRY_RUN = not args.live
    
    logging.info("Starting Inventory Reconciliation...")
    if DRY_RUN:
        logging.info("!!! DRY RUN MODE - No changes will be made !!!")
    else:
        logging.info("!!! LIVE MODE - INVENTORY WILL BE OVERWRITTEN !!!")

    # Load Cache
    cache = load_cache()

    # Read CSV
    try:
        with open(args.csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        logging.error(f"Could not read CSV: {e}")
        return

    logging.info(f"Loaded {len(rows)} rows from {args.csv_file}")

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(60000)
        except Exception as e:
            logging.error(f"Error connecting to Chrome: {e}")
            return

        for i, row in enumerate(rows):
            # 1. Identify Product ID
            pid = row.get('Product ID') or row.get('TCGPlayer ID')
            scry_id = row.get('Scryfall ID')
            name = row.get('Name', 'Unknown')
            
            # If no PID, try to get from Scryfall ID
            if not pid and scry_id:
                logging.info(f"[{i+1}] Resolving ID for {name} via Scryfall...")
                pid = get_tcgplayer_id_from_scryfall(scry_id, cache)
                if pid:
                    save_cache(cache)
            
            # If still no PID, try to SEARCH by Name
            if not pid and name and name != "Unknown":
                pid = search_product_id(page, name)
                if pid:
                    logging.info(f"  Found ID via Search: {pid}")
            
            if not pid:
                logging.warning(f"[{i+1}] SKIPPING {name}: No Product ID found (Scryfall or Search).")
                continue

            # 2. Target Data
            target_qty = int(row.get('Qty', 0))
            # Normalize condition text (e.g. "Near Mint" -> "Near Mint")
            target_variant = row.get('Variant') or row.get('Condition', '')
            
            logging.info(f"[{i+1}/{len(rows)}] Reconciling {name} (ID: {pid}) -> {target_variant}: {target_qty}")

            # 3. Navigate
            url = f"https://store.tcgplayer.com/admin/product/manage/{pid}"
            try:
                page.goto(url)
                page.wait_for_load_state('domcontentloaded')
            except Exception as e:
                logging.error(f"  Navigation failed: {e}")
                continue

            # 4. Find Row
            rows_elements = page.locator("table tbody tr").all()
            target_row_found = False
            changes_made = False

            for r in rows_elements:
                try:
                    # Check Variant Name
                    variant_text = r.locator("td").first.text_content().strip()
                    
                    # Simple fuzzy match or exact match
                    # The CSV 'Variant' might be "Near Mint Foil" or just "Near Mint"
                    # We need to be careful.
                    # Strict Variant Matching
                    # Ensure "Foil" status matches exactly
                    target_is_foil = "foil" in target_variant.lower()
                    row_is_foil = "foil" in variant_text.lower()
                    
                    if target_is_foil != row_is_foil:
                        continue
                        
                    # Check if the base condition matches (e.g. "Near Mint")
                    # Remove "Foil" from both to compare base condition
                    target_base = target_variant.lower().replace("foil", "").strip()
                    row_base = variant_text.lower().replace("foil", "").strip()
                    
                    if target_base not in row_base:
                        continue
                    
                    # Found the row!
                    target_row_found = True
                    
                    # Check Current Qty
                    inputs = r.locator("input[type='text']").all()
                    if not inputs: continue
                    qty_input = inputs[-1]
                    
                    current_qty_val = qty_input.input_value()
                    current_qty = int(current_qty_val) if current_qty_val.isdigit() else 0
                    
                    # UPDATE QUANTITY
                    if current_qty != target_qty:
                        logging.info(f"    Qty Mismatch: Store {current_qty} vs CSV {target_qty} -> Updating...")
                        if not DRY_RUN:
                            qty_input.fill(str(target_qty))
                            changes_made = True
                    else:
                        logging.info(f"    Qty Match: {current_qty}")

                    # UPDATE PRICE (Always Match Market while we are here)
                    match_buttons = r.locator("button, input[type='button'], a.btn").filter(has_text="Match").all()
                    if not match_buttons: match_buttons = r.locator("text=Match").all()
                    
                    if len(match_buttons) >= 1:
                        market_btn = match_buttons[2] if len(match_buttons) >= 3 else match_buttons[-1]
                        if not DRY_RUN:
                            market_btn.click()
                            changes_made = True
                            # Optional: Check for anomalies here?
                    
                    break # Stop looking for rows once found
                except Exception as e:
                    pass
            
            if not target_row_found:
                logging.warning(f"  Could not find variant row for '{target_variant}'")

            # 5. Save
            if changes_made and not DRY_RUN:
                save_btn = page.get_by_role("button", name="Save", exact=True).first
                if save_btn.is_visible():
                    save_btn.click()
                    time.sleep(2.5)
                    logging.info("  Saved.")
            elif changes_made and DRY_RUN:
                logging.info("  [Dry Run] Would have saved.")

    logging.info("Reconciliation Complete.")

if __name__ == "__main__":
    main()
