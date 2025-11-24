import csv
import time
import logging
import datetime
import requests
import json
import os
import argparse
from playwright.sync_api import sync_playwright

CSV_FILE = 'spm_for_store.csv'
CACHE_FILE = 'tcg_id_cache.json'
# DRY_RUN is now handled via args
LOG_FILE = f"upload_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

# Setup logging
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='w'
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger('').addHandler(console)

# Mappings
CONDITION_MAP = {
    'near_mint': 'Near Mint',
    'lightly_played': 'Lightly Played',
    'moderately_played': 'Moderately Played',
    'heavily_played': 'Heavily Played',
    'damaged': 'Damaged'
}

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f)

def get_tcgplayer_id(scryfall_id, cache):
    if scryfall_id in cache:
        return cache[scryfall_id]
    
    url = f"https://api.scryfall.com/cards/{scryfall_id}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            tcg_id = data.get('tcgplayer_id')
            cache[scryfall_id] = tcg_id
            time.sleep(0.1) # Rate limit
            return tcg_id
    except Exception as e:
        logging.error(f"Scryfall API error for {scryfall_id}: {e}")
    return None

def main():
    parser = argparse.ArgumentParser(description="Upload Cards to TCGPlayer")
    parser.add_argument("--live", action="store_true", help="Actually upload cards (disable dry run)")
    args = parser.parse_args()
    
    global DRY_RUN
    DRY_RUN = not args.live

    logging.info("Starting TCGPlayer Uploader (Direct ID Method)...")
    if DRY_RUN:
        logging.info("!!! DRY RUN MODE ACTIVE - NO CHANGES WILL BE SAVED (Use --live to execute) !!!")
    else:
        logging.info("!!! LIVE MODE - INVENTORY WILL BE UPDATED !!!")
    
    print("IMPORTANT: Ensure you have launched Chrome with: --remote-debugging-port=9222")
    
    # 1. Load CSV and Fetch IDs
    logging.info("Loading CSV and fetching TCGPlayer IDs...")
    cache = load_cache()
    cards_to_process = []
    
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        raw_cards = list(reader)
        
    print(f"Fetching IDs for {len(raw_cards)} cards (this may take a moment)...")
    for i, card in enumerate(raw_cards):
        sid = card['Scryfall ID']
        if sid:
            tid = get_tcgplayer_id(sid, cache)
            if tid:
                card['tcg_id'] = tid
                cards_to_process.append(card)
            else:
                logging.warning(f"Could not find TCGPlayer ID for {card['Name']}")
        
        if i % 10 == 0:
            print(f"  Processed {i}/{len(raw_cards)}...")
            
    save_cache(cache)
    logging.info(f"Ready to process {len(cards_to_process)} cards.")
    
    # 2. Browser Automation
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            logging.info("Connected to Chrome.")
        except Exception as e:
            logging.error(f"Could not connect to Chrome: {e}")
            print("ERROR: Could not connect to Chrome. Make sure it is running with --remote-debugging-port=9222")
            return

        print("\n" + "="*50)
        print("ACTION REQUIRED: Log in to TCGPlayer if needed.")
        print("Press ENTER to start processing...")
        print("="*50 + "\n")
        input()
        
        for i, card in enumerate(cards_to_process):
            try:
                process_card(page, card, i + 1, len(cards_to_process))
            except Exception as e:
                logging.error(f"Error processing {card['Name']}: {e}")

    logging.info("Done! Check log file.")
    input("Press Enter to close...")

def process_card(page, card, index, total):
    name = card['Name']
    tcg_id = card['tcg_id']
    condition_raw = card['Condition']
    foil_raw = card['Foil']
    qty = card['Quantity']
    
    condition = CONDITION_MAP.get(condition_raw, 'Near Mint')
    is_foil = foil_raw.lower() == 'foil'
    
    logging.info(f"[{index}/{total}] Processing: {name} (ID: {tcg_id}) - {condition} {'Foil' if is_foil else ''}")
    
    # Direct Navigation
    url = f"https://store.tcgplayer.com/admin/product/manage/{tcg_id}"
    page.goto(url)
    
    # Wait for page load
    try:
        page.wait_for_selector("h2", timeout=5000) # Wait for header
    except:
        pass

    # The "Manage" page lists all printings/conditions.
    # We need to find the row that matches our Condition and Foil status.
    
    # This is tricky because the table structure varies.
    # Usually there is a table with columns: "Product Name", "Condition", "Price", "Qty", etc.
    # Or separate tables for Foil vs Normal.
    
    # We will try to find a row that contains our Condition text.
    # And if Foil, we look for "Foil" in the row or section.
    
    # DEBUG: For the first card, let's pause to inspect selectors if needed.
    if index == 1:
        logging.info("  [DEBUG] Inspecting Manage Page layout...")
        # time.sleep(5) 

    # Logic to find the input box for Quantity and Price
    # This is highly dependent on the DOM.
    # Based on standard TCGPlayer Manage page:
    # Rows have a "Condition" cell.
    # Inputs have names like "Quantity", "Price".
    
    # Placeholder logic:
    # 1. Find row with text "Near Mint" (and "Foil" if applicable)
    # 2. Within that row, find the "Match Market" button and "Add" button?
    
    # Since I can't see the DOM, I will log that we arrived.
    # Real implementation needs the exact selectors for the "Manage" table.
    
    logging.info("  Arrived at Manage Page.")
    
    # Wait for table
    try:
        page.wait_for_selector("table.product-list", timeout=10000) # Guessing class, or just wait for 'tr'
    except:
        pass

    # Get all rows
    rows = page.locator("table tbody tr").all()
    logging.info(f"  Found {len(rows)} rows.")
    
    target_row_found = False
    
    # Construct the exact text we are looking for in the first column
    # Based on screenshot: "Near Mint", "Lightly Played", "Near Mint Foil", "Lightly Played Foil"
    target_condition_text = condition
    if is_foil:
        target_condition_text += " Foil"
        
    logging.info(f"  Target Row Text: '{target_condition_text}'")

    # Data collection for Anomaly Check
    prices = {} # { 'Near Mint': 10.0, 'Lightly Played': 12.0, ... }
    rows_map = {} # { 'Near Mint': row_object, ... }

    for row in rows:
        try:
            row_text = row.locator("td").first.text_content().strip()
            
            # Store row for later access
            # Normalize text to just the condition part for easier mapping if needed
            # But for now, we use the full text as key (e.g. "Near Mint Foil")
            rows_map[row_text] = row
            
            # Extract Market Price
            # Assuming Market Price is in the 4th column (index 3) or similar
            # We can look for the cell with "TCG Market Price" header alignment, 
            # or just grab the text from the cell that looks like a price
            
            # Based on screenshot, Market Price is a column. Let's try to find it.
            # It's usually the column before the "Match" button for Market Price.
            # Or we can just grab all text in the row and regex for prices?
            # Let's try getting the cell by index. 
            # Columns: Condition, Lowest Listing, Last Sold, Market Price, Marketplace Price, Qty
            # Index: 0, 1, 2, 3, 4, 5
            
            market_price_cell = row.locator("td").nth(3) 
            price_text = market_price_cell.text_content().strip()
            # Clean price: "$0.04" -> 0.04
            price_val = 0.0
            if '$' in price_text:
                try:
                    price_val = float(price_text.replace('$', '').replace(',', ''))
                except:
                    pass
            prices[row_text] = price_val
            
        except:
            continue

    # --- Anomaly Check ---
    # Only relevant if we are listing as "Near Mint"
    # We want to check if "Lightly Played" (of same foil status) is higher.
    
    check_foil_suffix = " Foil" if is_foil else ""
    nm_key = f"Near Mint{check_foil_suffix}"
    lp_key = f"Lightly Played{check_foil_suffix}"
    
    if condition == "Near Mint" and nm_key in prices and lp_key in prices:
        nm_price = prices[nm_key]
        lp_price = prices[lp_key]
        
        if lp_price > nm_price:
            logging.warning(f"  [ANOMALY] LP (${lp_price}) is higher than NM (${nm_price})!")
            print(f"\n  !!! PRICING ANOMALY DETECTED !!!")
            print(f"  Card: {name}")
            print(f"  Near Mint:      ${nm_price}")
            print(f"  Lightly Played: ${lp_price}")
            print(f"  You are currently listing as: {condition}")
            
            if not DRY_RUN:
                choice = input("  >>> Switch listing to 'Lightly Played' to capture higher price? (y/n): ")
                if choice.lower() == 'y':
                    logging.info("  User chose to downgrade to LP for higher price.")
                    target_condition_text = lp_key # Switch target
                    # Update condition variable for logging consistency if needed
                    condition = "Lightly Played" 

    # --- End Anomaly Check ---

    for row in rows:
        try:
            row_text = row.locator("td").first.text_content().strip()
        except:
            continue
            
        # 1. Check if this is our TARGET row (potentially updated by anomaly check)
        is_target = (row_text == target_condition_text)
        
        # 2. Check if we should update price (if we have stock OR if it's our target)
        qty_input = row.locator("input[type='text']").last
        
        try:
            current_qty_str = qty_input.input_value()
            current_qty = int(current_qty_str) if current_qty_str.isdigit() else 0
        except:
            current_qty = 0
            
        if current_qty > 0 or is_target:
            # Find the "Match" button for Market Price.
            # Use robust selector from inventory_sync.py
            match_buttons = row.locator("button, input[type='button'], a.btn").filter(has_text="Match").all()
            
            if not match_buttons:
                 match_buttons = row.locator("text=Match").all()
            
            if len(match_buttons) >= 1:
                if len(match_buttons) >= 3:
                    market_match_btn = match_buttons[2]
                else:
                    market_match_btn = match_buttons[-1]
                
                if not DRY_RUN:
                    market_match_btn.click()
            else:
                pass

        # 3. Update Quantity for TARGET row
        if is_target:
            target_row_found = True
            new_qty = current_qty + int(qty)
            
            logging.info(f"  [UPDATE] {row_text}: Qty {current_qty} -> {new_qty}")
            
            if not DRY_RUN:
                qty_input.fill(str(new_qty))
                
    if not target_row_found:
        logging.warning(f"  Could not find row for '{target_condition_text}'")
        return

    # 4. Save
    if not DRY_RUN:
        # Find the Save button at the top or bottom
        save_btn = page.get_by_role("button", name="Save", exact=True).first
        if save_btn.is_visible():
            save_btn.click()
            logging.info("  Clicked Save.")
            # Wait for save to complete (spinner or page reload)
            time.sleep(2.5) 
        else:
            logging.error("  Could not find Save button!")
    else:
        logging.info("  [DRY RUN] Would click Save.")
        time.sleep(1) # Pause for visual verification
