import csv
import time
import logging
import datetime
import re
import os
from playwright.sync_api import sync_playwright

# Configuration
OUTPUT_DIR = "output"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"tcg_inventory_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

def main():
    print("Starting Inventory Downloader...")
    print("IMPORTANT: Ensure Chrome is running with --remote-debugging-port=9222")
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(60000)
        except Exception as e:
            print(f"Error connecting to Chrome: {e}")
            return

        print("Navigating to Catalog...")
        page.goto("https://store.tcgplayer.com/admin/product/catalog")
        
        # 1. Setup Filters
        print("Setting up filters...")
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
        except Exception as e:
            print(f"  Error setting filters: {e}")

        print("\n" + "="*50)
        print("VERIFICATION REQUIRED:")
        print("1. Is 'My Inventory Only' checked?")
        print("2. Are results visible?")
        print("3. (Optional) Set 'Items per page' to 100 or 500 for speed.")
        print("Press ENTER to start scraping...")
        print("="*50 + "\n")
        input()
        
        # 2. Scrape Loop
        all_products = []
        page_num = 1
        
        while True:
            print(f"Scraping Page {page_num}...")
            
            # Wait for table
            try:
                page.wait_for_selector("table tbody tr", timeout=5000)
            except:
                print("  No table found. Ending.")
                break
            
            # Use evaluate to scrape the whole table at once (MUCH faster/robust)
            page_data = page.evaluate(r"""() => {
                const rows = Array.from(document.querySelectorAll("table tbody tr"));
                return rows.map(row => {
                    const cells = Array.from(row.querySelectorAll("td"));
                    if (cells.length < 5) return null;
                    
                    // Try to find Product ID from the 'Manage' link or checkbox
                    let pid = "";
                    const manageLink = row.querySelector("a[href*='/admin/product/manage/']");
                    if (manageLink) {
                        const match = manageLink.getAttribute('href').match(/manage\/(\d+)/);
                        if (match) pid = match[1];
                    }
                    
                    // Name is usually in the 2nd column (index 1), often inside a link or strong tag
                    const name = cells[1] ? cells[1].innerText.trim() : "Unknown";
                    const set = cells[2] ? cells[2].innerText.trim() : "Unknown";
                    
                    return {
                        'Product ID': pid,
                        'Name': name,
                        'Set': set,
                        'Raw Data': row.innerText.replace(/\t/g, ' ').replace(/\n/g, ' | ')
                    };
                }).filter(item => item !== null && item['Product ID'] !== "");
            }""")
            
            print(f"  Found {len(page_data)} items.")
            all_products.extend(page_data)
            
            # Next Page
            
            # Next Page
            try:
                next_btn = page.get_by_role("link", name="Next", exact=True)
                if next_btn.is_visible() and "disabled" not in next_btn.get_attribute("class", ""):
                    next_btn.click()
                    page_num += 1
                    time.sleep(2) # Wait for load
                else:
                    print("  End of catalog.")
                    break
            except:
                break
        
        # 3. Save to CSV
        print(f"Saving {len(all_products)} items to {OUTPUT_CSV}...")
        if all_products:
            keys = ['Product ID', 'Name', 'Set', 'Raw Data']
            with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(all_products)
                
        print("Done!")

if __name__ == "__main__":
    main()
