import time
from playwright.sync_api import sync_playwright

IDS = ["614199", "614344", "615410", "614429", "644702"]

def main():
    print("Starting Name Extraction Test...")
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()
        
        for pid in IDS:
            print(f"\nTesting ID: {pid}")
            page.goto(f"https://store.tcgplayer.com/admin/product/manage/{pid}")
            page.wait_for_load_state('domcontentloaded')
            
            # Save HTML for inspection
            if pid == IDS[0]:
                with open("debug_page.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                print("  Saved debug_page.html")

            # 1. Try data-bind="text: productName"
            print("  Strategy 1 (Knockout Bind):")
            spans = page.locator("span[data-bind='text: productName']").all()
            for span in spans:
                text = span.text_content().strip()
                if text:
                    print(f"    Found SPAN: {text}")
                    break
            
            # 2. Try Link Title
            print("  Strategy 2 (Link Title):")
            link = page.locator("a.blue-button-sm").first
            if link.is_visible():
                title = link.get_attribute("title")
                if title:
                    # "View all live prices for [NAME] in a new tab!"
                    name = title.replace("View all live prices for ", "").replace(" in a new tab!", "")
                    print(f"    Found LINK Title: {name}")

            # 3. Try H1 (just in case)
            print("  Strategy 3 (H1):")
            if page.locator("h1").count() > 0:
                print(f"    H1: {page.locator('h1').first.text_content().strip()}")

if __name__ == "__main__":
    main()
