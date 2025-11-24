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

def get_tcgplayer_id_from_pokemon_api(card_name, set_name, cache):
    # Check cache first
    cache_key = f"pokemon_{card_name}_{set_name}"
    if cache_key in cache:
        return cache[cache_key]

    logging.info(f"  Searching Pokemon API for: {card_name}...")
    url = "https://api.pokemontcg.io/v2/cards"
    headers = {'X-Api-Key': POKEMON_API_KEY}
    
    # Construct query
    query = f'name:"{card_name}"'
    params = {'q': query, 'pageSize': 10}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if data['count'] == 0:
            logging.info("    No matches found.")
            return None
            
        # Filter by set name if provided
        best_match = None
        if set_name:
            for card in data['data']:
                api_set = card['set']['name']
                # Simple fuzzy match
                if set_name.lower() in api_set.lower() or api_set.lower() in set_name.lower():
                    best_match = card
                    break
        
        if not best_match:
            best_match = data['data'][0] # Fallback
            
        # Get TCGPlayer URL
        tcg_data = best_match.get('tcgplayer', {})
        tcg_url = tcg_data.get('url')
        
        if tcg_url:
            # Follow redirect to get numeric ID
            try:
                logging.info(f"    Resolving TCGPlayer URL: {tcg_url}...")
                r = requests.head(tcg_url, allow_redirects=True, timeout=10)
                final_url = r.url
                
                # Extract ID: https://www.tcgplayer.com/product/123456/...
                import re
                match = re.search(r'/product/(\d+)', final_url)
                if match:
                    tcg_id = match.group(1)
                    logging.info(f"    -> Found ID: {tcg_id}")
                    cache[cache_key] = tcg_id
                    return tcg_id
                else:
                    logging.warning("    -> Could not extract ID from resolved URL.")
            except Exception as e:
                logging.error(f"    -> Error resolving URL: {e}")
        else:
            logging.info("    No TCGPlayer URL in API response.")

    except Exception as e:
        logging.error(f"    Pokemon API Error: {e}")
        
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
            category = row.get('Category', '')
            set_name = row.get('Set', '')
            
            # If no PID, try to resolve
            if not pid:
                # Strategy 1: Scryfall (for Magic)
                if scry_id:
                    logging.info(f"[{i+1}] Resolving ID for {name} via Scryfall...")
                    pid = get_tcgplayer_id_from_scryfall(scry_id, cache)
                
                # Strategy 2: Pokemon API (for Pokemon)
                elif category == "Pokemon" or "Pokemon" in category:
                    logging.info(f"[{i+1}] Resolving ID for {name} via Pokemon API...")
                    pid = get_tcgplayer_id_from_pokemon_api(name, set_name, cache)
                
                # Strategy 3: Search by Name (Fallback)
                if not pid and name and name != "Unknown":
                    pid = search_product_id(page, name)
                    if pid:
                        logging.info(f"  Found ID via Search: {pid}")
                
                if pid:
                    save_cache(cache)
            
            if not pid:
                logging.warning(f"[{i+1}] SKIPPING {name}: No Product ID found.")
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
