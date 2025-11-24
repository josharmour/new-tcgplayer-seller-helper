import csv
import time
import logging
import datetime
import re
import argparse
import json
import os
from playwright.sync_api import sync_playwright

# Configuration
OUTPUT_DIR = "output"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

HARVEST_FILE = os.path.join(OUTPUT_DIR, "harvest_latest.json")
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "progress_latest.json")

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

def main():
    parser = argparse.ArgumentParser(description="Sync TCGPlayer Inventory Prices")
    parser.add_argument("--live", action="store_true", help="Actually update prices (disable dry run)")
    parser.add_argument("--resume", action="store_true", help="Resume from last progress")
    args = parser.parse_args()
    
    DRY_RUN = not args.live

    print("Starting Inventory Sync & Price Matcher...")
    if DRY_RUN:
        print("!!! DRY RUN MODE - No prices will be changed (Use --live to execute) !!!")
    else:
        print("!!! LIVE MODE - PRICES WILL BE UPDATED !!!")
    
    print("IMPORTANT: Ensure Chrome is running with --remote-debugging-port=9222")
    
    product_ids = []
    start_index = 0
    report_file_path = ""
    
    # Stats tracking
    total_items = 0
    total_changes = 0
    total_value_delta = 0.0

    # --- INITIALIZATION & RESUME LOGIC ---
    if args.resume:
        if os.path.exists(PROGRESS_FILE) and os.path.exists(HARVEST_FILE):
            print("\n--- RESUMING PREVIOUS SESSION ---")
            try:
                with open(PROGRESS_FILE, 'r') as f:
                    progress = json.load(f)
                
                last_id = progress.get('last_processed_id')
                report_file_path = progress.get('report_file')
                
                with open(HARVEST_FILE, 'r') as f:
                    product_ids = json.load(f)
                
                if last_id in product_ids:
                    start_index = product_ids.index(last_id) + 1
                    print(f"Resuming after ID {last_id} (Index {start_index}/{len(product_ids)})")
                    print(f"Appending to report: {report_file_path}")
                else:
                    print(f"Last ID {last_id} not found in harvest list. Starting from beginning.")
                    start_index = 0
                    
            except Exception as e:
                print(f"Error resuming: {e}. Starting fresh.")
                args.resume = False # Fallback
        else:
            print("No progress file found. Starting fresh.")
            args.resume = False

    if not args.resume:
        # Fresh Start
        report_file_path = os.path.join(OUTPUT_DIR, f"inventory_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        
        # --- PHASE 1: HARVEST IDs ---
        with sync_playwright() as p:
            try:
                browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(60000)
            except Exception as e:
                print(f"Error connecting to Chrome: {e}")
                return

            print("\n--- PHASE 1: Harvesting Product IDs ---")
            page.goto("https://store.tcgplayer.com/admin/product/catalog")
            
            # Automate Filters
            print("Setting filters...")
            try:
                my_inv = page.get_by_label("My Inventory Only", exact=False)
                if not my_inv.is_visible():
                    my_inv = page.locator("label", has_text="My Inventory Only").locator("..").locator("input")
                
                if my_inv.is_visible() and not my_inv.is_checked():
                    my_inv.check()
                    print("  Checked 'My Inventory Only'")
                
                search_btn = page.get_by_role("button", name="Search", exact=True)
                if search_btn.is_visible():
                    search_btn.click()
                    print("  Clicked Search")
                    page.wait_for_selector("table tbody tr", timeout=10000)
                else:
                    print("  Could not find Search button.")
            except Exception as e:
                print(f"  Error setting filters: {e}")

            print("\n" + "="*50)
            print("VERIFICATION REQUIRED:")
            print("Please check the browser window.")
            print("1. Is 'My Inventory Only' checked?")
            print("2. Did the search results load?")
            print("If not, please fix the filters and click Search manually.")
            input("Press ENTER to start harvesting IDs...")
            print("="*50 + "\n")
            
            while True:
                print("Scanning page for products...")
                # Extract rich data from the table rows
                page_items = page.evaluate("""() => {
                    // Find the table with "Product Name" in the header
                    const tables = Array.from(document.querySelectorAll("table"));
                    const productTable = tables.find(t => t.innerText.includes("Product Name"));
                    if (!productTable) return [];

                    const rows = Array.from(productTable.querySelectorAll("tbody tr"));
                    return rows.map(row => {
                        const cells = Array.from(row.querySelectorAll("td"));
                        if (cells.length < 5) return null;
                        
                        // Product ID from Link (usually in the 'View' column or 'Actions')
                        let pid = "";
                        const link = row.querySelector("a[href*='/admin/product/manage/']");
                        if (link) {
                            const match = link.getAttribute('href').match(/manage\/(\d+)/);
                            if (match) pid = match[1];
                        }
                        if (!pid) return null;

                        // Correct Column Indices based on inspection:
                        // 0: Product Line (Category)
                        // 1: View (Image/Link)
                        // 2: Product Name
                        // 3: Set
                        // 4: Rarity
                        // 5: Number
                        
                        const category = cells[0] ? cells[0].innerText.trim() : "Unknown";
                        const name = cells[2] ? cells[2].innerText.trim() : "Unknown";
                        const set = cells[3] ? cells[3].innerText.trim() : "Unknown";
                        const rarity = cells[4] ? cells[4].innerText.trim() : "";
                        const number = cells[5] ? cells[5].innerText.trim() : "";
                        
                        return {
                            id: pid,
                            name: name,
                            set: set,
                            category: category,
                            rarity: rarity,
                            number: number
                        };
                    }).filter(item => item !== null);
                }""")
                
                new_count = 0
                for item in page_items:
                    # Check if ID already exists in our list
                    if not any(existing['id'] == item['id'] for existing in product_ids):
                        product_ids.append(item)
                        new_count += 1
                
                print(f"  Found {new_count} new products on this page.")
                
                try:
                    next_btn = page.get_by_role("link", name="Next", exact=True)
                    if next_btn.is_visible() and "disabled" not in next_btn.get_attribute("class", ""):
                        next_btn.click()
                        time.sleep(1) 
                    else:
                        print("  End of catalog.")
                        break
                except:
                    break
            
            print(f"Total Products Found: {len(product_ids)}")
            
            # Save Harvest List (Rich Data)
            with open(HARVEST_FILE, 'w') as f:
                json.dump(product_ids, f)
            
            # Initialize Report File
            with open(report_file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['Product ID', 'Name', 'Set', 'Category', 'Number', 'Rarity', 'Variant', 'Qty', 'Old Price', 'New Price', 'Status'])
                writer.writeheader()

    # --- PHASE 2: PROCESS & UPDATE ---
    print("\n--- PHASE 2: Processing & Updating Prices ---")
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(60000)
        except Exception as e:
            print(f"Error connecting to Chrome: {e}")
            return

        for i in range(start_index, len(product_ids)):
            item = product_ids[i]
            # Handle both old format (string) and new format (dict) for backward compatibility
            if isinstance(item, dict):
                pid = item['id']
                catalog_set = item.get('set', '')
                catalog_cat = item.get('category', '')
                catalog_rarity = item.get('rarity', '')
                catalog_number = item.get('number', '')
            else:
                pid = item
                catalog_set = ""
                catalog_cat = ""
                catalog_rarity = ""
                catalog_number = ""

            print(f"[{i+1}/{len(product_ids)}] Processing ID: {pid}")
            
            url = f"https://store.tcgplayer.com/admin/product/manage/{pid}"
            
            # Retry Logic
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    page.goto(url, timeout=45000)
                    break
                except Exception as e:
                    print(f"  Navigation failed (Attempt {attempt+1}/{max_retries}): {e}")
                    time.sleep(5)
            else:
                print("  Skipping this card due to repeated timeouts.")
                continue
            
            try:
                page.wait_for_load_state('domcontentloaded', timeout=10000)
            except:
                pass

            # Check for table
            try:
                if not page.locator("table").first.is_visible():
                    print("  No table found on page. Skipping.")
                    continue
            except:
                pass
            
            product_name = "Unknown"
            try:
                # Strategy 1: Knockout data-bind (Most reliable)
                span = page.locator("span[data-bind='text: productName']").first
                if span.is_visible():
                    product_name = span.text_content().strip()
                
                # Strategy 2: Link Title
                if not product_name or product_name == "Unknown":
                    link = page.locator("a.blue-button-sm").first
                    if link.is_visible():
                        title_attr = link.get_attribute("title")
                        if title_attr:
                            product_name = title_attr.replace("View all live prices for ", "").replace(" in a new tab!", "").strip()

                # Strategy 3: H1 (Fallback)
                if not product_name or product_name == "Unknown":
                    h1 = page.locator("h1").first
                    if h1.is_visible():
                        text = h1.text_content().strip()
                        if text and "Seller Portal" not in text:
                            product_name = text
                
                # Strategy 4: Page Title (Last Resort)
                if not product_name or product_name == "Unknown":
                    title = page.title()
                    if "-" in title:
                        product_name = title.split("-")[1].strip()
                    elif "Seller Portal" not in title:
                        product_name = title

                # Use Catalog Data for Set/Category/Rarity/Number
                set_name = catalog_set
                category = catalog_cat
                rarity = catalog_rarity
                number = catalog_number
                
                # Fallback Extraction if Catalog Data is missing
                if not set_name:
                    try:
                        set_label = page.locator(".pInfo label", has_text="Set Name").first
                        if set_label.is_visible():
                            full_text = set_label.locator("..").text_content().strip()
                            set_name = full_text.replace("Set Name", "").strip()
                    except: pass
                
                if not category:
                    try:
                        link = page.locator("a.blue-button-sm").first
                        if link.is_visible():
                            href = link.get_attribute("href")
                            if href and "/product/" in href:
                                parts = href.split(f"/product/{pid}/")
                                if len(parts) > 1:
                                    slug = parts[1]
                                    if slug.startswith("magic"): category = "Magic: The Gathering"
                                    elif slug.startswith("pokemon"): category = "Pokemon"
                                    elif slug.startswith("yugioh"): category = "Yu-Gi-Oh!"
                                    elif slug.startswith("lorcana"): category = "Lorcana"
                                    elif slug.startswith("star-wars"): category = "Star Wars"
                                    else: category = slug.split("-")[0].capitalize()
                    except: pass

                print(f"  Product: {product_name} | Set: {set_name} | Cat: {category} | #: {number}")
            except:
                pass
            
            rows = page.locator("table tbody tr").all()
            print(f"  Found {len(rows)} variant rows.")
            changes_made = False
            
            # Process Rows
            for row in rows:
                try:
                    inputs = row.locator("input[type='text']").all()
                    if not inputs: continue
                    qty_input = inputs[-1]
                    if not qty_input.is_visible(): continue
                    qty_val = qty_input.input_value(timeout=500)
                    
                    if not qty_val.isdigit() or int(qty_val) <= 0:
                        continue
                    
                    current_qty = int(qty_val)
                    
                    # Extract Variant Name
                    variant_name = row.locator("td").first.text_content().strip()
                    
                    # --- PRICE UPDATE LOGIC ---
                    match_btns = row.locator("input[value='Match']").all()
                    
                    old_price = "N/A"
                    new_price = "N/A"
                    
                    if len(match_btns) >= 3:
                        market_btn = match_btns[2] # 0-indexed, so 3rd button
                        
                        price_input = row.locator("input[data-bind*='textInput: newPrice']").first
                        if price_input.is_visible():
                            old_price = price_input.input_value()
                        
                        if not DRY_RUN:
                            market_btn.click()
                            if price_input.is_visible():
                                new_price = price_input.input_value()
                            changes_made = True
                            status = "Updated"
                        else:
                            status = "Dry Run"
                            
                        print(f"      {variant_name}: Qty {current_qty} | {old_price} -> {new_price}")
                        
                        # Add to Inventory List
                        row_data = {
                            'Product ID': pid,
                            'Name': product_name,
                            'Set': set_name,
                            'Category': category,
                            'Number': number,
                            'Rarity': rarity,
                            'Variant': variant_name,
                            'Qty': current_qty,
                            'Old Price': old_price,
                            'New Price': new_price,
                            'Status': status
                        }
                        
                        with open(report_file_path, 'a', newline='', encoding='utf-8') as f:
                            writer = csv.DictWriter(f, fieldnames=['Product ID', 'Name', 'Set', 'Category', 'Number', 'Rarity', 'Variant', 'Qty', 'Old Price', 'New Price', 'Status'])
                            writer.writerow(row_data)

                        # Update Stats
                        total_items += 1
                        try:
                            o_p = float(str(old_price).replace('$','').replace(',',''))
                            n_p = float(str(new_price).replace('$','').replace(',',''))
                            if abs(n_p - o_p) > 0.001:
                                total_changes += 1
                                total_value_delta += (n_p - o_p) * int(current_qty)
                        except:
                            pass
                    else:
                        print(f"      {variant_name}: Qty {current_qty} | No Match Button Found")

                except Exception as e:
                    pass
            
            if changes_made and not DRY_RUN:
                save_btn = page.get_by_role("button", name="Save", exact=True).first
                if save_btn.is_visible():
                    save_btn.click()
                    time.sleep(2.5) 
                    print("  Saved.")
            
            # Update Progress
            with open(PROGRESS_FILE, 'w') as f:
                json.dump({
                    'last_processed_id': pid,
                    'report_file': report_file_path,
                    'timestamp': str(datetime.datetime.now())
                }, f)

    # --- SUMMARY ---
    print("="*40 + "\n")

if __name__ == "__main__":
    main()
