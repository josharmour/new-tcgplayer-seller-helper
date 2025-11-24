# Workflow: Adding New Cards to Inventory

This guide explains how to add new cards to your TCGPlayer inventory using the "Master CSV" method.

## Prerequisites
1.  You have generated a Master CSV using `inventory_sync.py`.
2.  You have the physical cards ready to add.

## Steps

1.  **Open your Master CSV** (e.g., `output/inventory_report_LATEST.csv`) in Excel or a text editor.
    *   *Note: If `inventory_sync.py` is currently running, wait for it to finish.*

2.  **Add New Rows** for the new cards.
    *   **Product ID**: Leave blank (the script will find it).
    *   **Name**: Enter the exact card name (e.g., "Black Lotus").
    *   **Variant**: Enter the Condition and Foil status (e.g., "Near Mint" or "Near Mint Foil").
    *   **Qty**: Enter the quantity you have.
    *   **Price**: You can leave this blank or set a target price. The script will match Market Price automatically if configured.

    **Example Rows:**
    | Product ID | Name | Variant | Qty | Price |
    | :--- | :--- | :--- | :--- | :--- |
    | | Black Lotus | Near Mint | 1 | |
    | | Sol Ring | Lightly Played Foil | 4 | |

3.  **Save the CSV**.

4.  **Run Reconciliation**:
    Run the reconciliation script in "Live" mode. It will:
    *   Read your CSV.
    *   Search for "Black Lotus" (since ID is missing).
    *   Find the correct Product ID.
    *   Update the quantity on TCGPlayer.
    
    ```powershell
    python reconcile_inventory.py output/inventory_report_LATEST.csv --live
    ```

5.  **Verify**:
    Check the logs or the TCGPlayer portal to ensure the cards were added.

## Tips
*   **Exact Names**: Try to use the exact name as it appears on TCGPlayer to ensure the search finds the correct card first.
*   **Foil**: Be careful to specify "Foil" in the Variant column if the card is foil.
