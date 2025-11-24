# TCGPlayer Inventory Automation

This project automates the management of your TCGPlayer Seller inventory. It bypasses the lack of "Mass Import" (Level 4) by using browser automation to interact with the Seller Portal directly.

## Prerequisites
- Python 3.13+
- Playwright
- Google Chrome (launched with remote debugging)

## Setup

1.  **Launch Chrome with Remote Debugging**:
    Open a terminal and run:
    ```powershell
    & "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\selenium\ChromeProfile"
    ```
    *Note: Close all other Chrome windows first.*

2.  **Log In**:
    In the opened Chrome window, log in to `sellerportal.tcgplayer.com`.

## Scripts & Workflow

### 1. `inventory_sync.py` (The "Master" Script)
**Purpose**: The core script for inventory management. It performs three functions:
1.  **Harvests IDs**: Scrapes your "My Inventory" to get a list of all Product IDs.
2.  **Updates Prices**: Visits each product page, matches the "Market Price", and saves the change.
3.  **Generates Master CSV**: Extracts the **exact product name** and variant details (Condition/Foil) to create a definitive `inventory_report_...csv`.

**Name Extraction Strategy**:
To ensure 100% accuracy, this script uses a robust fallback strategy:
1.  **Knockout JS Bind**: Extracts the name directly from the page's data model (`span[data-bind='text: productName']`).
2.  **Link Title**: Extracts the name from the "TCGplayer Live Prices" link title.
3.  **H1/Title**: Fallback for edge cases.

**Usage**:
```powershell
# Dry Run (Generate Report Only)
python inventory_sync.py

# Live Mode (Update Prices + Generate Report)
python inventory_sync.py --live

# Resume from a specific ID (if crashed)
python inventory_sync.py --live --resume-from 123456
```

### 2. `reconcile_inventory.py` (The "Sync" Script)
**Purpose**: Takes a CSV file (either the Master CSV or a custom list) and syncs it to TCGPlayer.
**Capabilities**:
*   **Updates Quantities**: Matches your CSV quantity to the store.
*   **Adds New Cards**: If `Product ID` is missing, it automatically finds the card using:
    1.  **Scryfall API** (for Magic: The Gathering).
    2.  **Pokémon TCG API** (for Pokémon).
    3.  **Admin Search** (Fallback for everything else).
*   **Strict Matching**: Ensures "Foil" cards are not confused with "Non-Foil".

**Usage**:
```powershell
python reconcile_inventory.py output/inventory_report_LATEST.csv --live
```

### 3. `upload_cards.py` (Legacy / Single Upload)
**Purpose**: Uploads *new* cards from a CSV file. Largely superseded by `reconcile_inventory.py` but useful for specific batch uploads.
**Usage**:
```powershell
python upload_cards.py --live
```

### 4. `download_inventory.py`
**Purpose**: A simpler script to just download the inventory catalog (IDs and Names) without visiting every product page. Useful for quick lookups.
**Usage**:
```powershell
python download_inventory.py
```

## Workflows

### Workflow A: Daily Maintenance
1.  Run `inventory_sync.py --live`.
2.  This updates all your prices to Market Price and gives you a fresh CSV report.

### Workflow B: Adding New Inventory
1.  Run `inventory_sync.py` to get a fresh Master CSV (optional, but recommended).
2.  Open the CSV in Excel.
3.  Add rows for your new cards.
    *   **Leave `Product ID` blank**.
    *   Enter **Name**, **Variant** (e.g. "Near Mint"), and **Qty**.
4.  Run `reconcile_inventory.py your_file.csv --live`.
5.  The script will find the IDs and add the cards.

## Output
All reports and logs are saved in the `output/` directory.
