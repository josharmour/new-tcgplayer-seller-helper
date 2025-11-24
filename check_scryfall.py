import csv
import requests
import time

CSV_FILE = 'spm_for_store.csv'

def check_scryfall_ids():
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        cards = list(reader)
        
    print(f"Checking first 5 cards from {len(cards)} total...")
    
    for i, card in enumerate(cards[:5]):
        scryfall_id = card['Scryfall ID']
        name = card['Name']
        
        if not scryfall_id:
            print(f"Skipping {name} (No Scryfall ID)")
            continue
            
        url = f"https://api.scryfall.com/cards/{scryfall_id}"
        try:
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                tcg_id = data.get('tcgplayer_id')
                print(f"Card: {name}")
                print(f"  Scryfall ID: {scryfall_id}")
                print(f"  TCGPlayer ID: {tcg_id}")
            else:
                print(f"Error fetching {name}: {response.status_code}")
        except Exception as e:
            print(f"Exception: {e}")
            
        # Be nice to Scryfall API
        time.sleep(0.1)

if __name__ == "__main__":
    check_scryfall_ids()
