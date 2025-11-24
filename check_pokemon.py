import requests
import re

def get_pokemon_tcg_id(card_name, set_id=None):
    """
    Searches for a Pokemon card and extracts the TCGPlayer ID.
    """
    api_url = "https://api.pokemontcg.io/v2/cards"
    headers = {"X-Api-Key": ""} # Optional: Add API key if rate limited
    
    params = {"q": f"name:\"{card_name}\""}
    if set_id:
        params["q"] += f" set.id:{set_id}"
        
    print(f"Searching for: {params['q']}...")
    
    try:
        response = requests.get(api_url, params=params, headers=headers)
        data = response.json()
        
        if "data" in data and len(data["data"]) > 0:
            # Just taking the first match for demo
            card = data["data"][0]
            print(f"Found: {card['name']} ({card['set']['name']})")
            
            if "tcgplayer" in card:
                url = card["tcgplayer"].get("url")
                print(f"TCGPlayer URL: {url}")
                
                # Extract ID from URL
                # Format: https://prices.pokemontcg.io/tcgplayer/42382
                if url:
                    match = re.search(r"tcgplayer/(\d+)", url)
                    if match:
                        return match.group(1)
            else:
                print("No TCGPlayer data found for this card.")
        else:
            print("No cards found.")
            
    except Exception as e:
        print(f"Error: {e}")
    
    return None

if __name__ == "__main__":
    # Test with a known card
    # Charizard from Base Set
    pid = get_pokemon_tcg_id("Charizard")
    print(f"Extracted ID: {pid}")
