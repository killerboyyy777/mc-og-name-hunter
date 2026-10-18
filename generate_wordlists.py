#!/usr/bin/env python3
"""Generate word lists filtered by Zipf frequency for rarity tiers."""

import wordfreq
from pathlib import Path

# Tier criteria based on mcindex.gg research
# Top: Zipf >= 4.5, length <= 6
# OG: Zipf >= 3.5, length <= 10
# Semi-OG: Zipf >= 2.5, length <= 16

TIER_CRITERIA = {
    "top": {"min_zipf": 4.5, "max_len": 6, "score": 80},
    "og": {"min_zipf": 3.5, "max_len": 10, "score": 60},
    "semi_og": {"min_zipf": 2.5, "max_len": 16, "score": 35},
}

# Stop words / function words to exclude (not good usernames)
# Only keep truly non-usable contractions and fragments
STOP_WORDS = {
    # Contractions without apostrophes (already filtered by ASCII check)
    "don", "won", "didn", "couldn", "wouldn", "shouldn", "cant", "wont",
    "isnt", "arent", "wasnt", "werent", "hasnt", "havent", "hadnt",
    "doesnt", "dont", "didnt", "couldnt", "wouldnt", "shouldnt", "mustnt",
    # Single letters (already filtered by length check)
}

# Valid Minecraft username characters: a-z, A-Z, 0-9, _
# Must be 3-16 chars
def is_valid_minecraft_name(name: str) -> bool:
    if not (3 <= len(name) <= 16):
        return False
    # Minecraft only allows ASCII letters, numbers, underscore
    return all(('a' <= c <= 'z') or ('A' <= c <= 'Z') or ('0' <= c <= '9') or c == '_' for c in name)

def get_zipf_frequency(word: str) -> float:
    """Get Zipf frequency for a word (English)."""
    try:
        return wordfreq.zipf_frequency(word.lower(), 'en')
    except Exception:
        return 0.0

def is_content_word(word: str) -> bool:
    """Check if word is likely a content word (noun, verb, adj, proper noun) not a function word."""
    word_lower = word.lower()
    if word_lower in STOP_WORDS:
        return False
    # Skip very short words that are likely function words
    if len(word) <= 2:
        return False
    return True

def categorize_word(word: str) -> str | None:
    """Return tier name if word fits criteria, else None."""
    word_lower = word.lower()
    zipf = get_zipf_frequency(word_lower)
    
    if zipf == 0:
        return None
    
    for tier_name, criteria in TIER_CRITERIA.items():
        if zipf >= criteria["min_zipf"] and len(word) <= criteria["max_len"]:
            return tier_name
    return None

def main():
    output_dir = Path("data/word_lists")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Get English word list from wordfreq
    # wordfreq uses a ~300k word list
    from wordfreq import top_n_list
    words = top_n_list('en', 100000)  # Top 100k English words
    
    tier_words = {tier: [] for tier in TIER_CRITERIA}
    
    for word in words:
        # Only keep valid Minecraft usernames (letters only for dictionary words)
        if not word.isalpha():
            continue
        if not is_valid_minecraft_name(word):
            continue
        if not is_content_word(word):
            continue
            
        tier = categorize_word(word)
        if tier:
            zipf = get_zipf_frequency(word)
            tier_words[tier].append((word.lower(), zipf))
    
    # Sort by Zipf descending (most common first), then by length ascending
    for tier in tier_words:
        tier_words[tier].sort(key=lambda x: (-x[1], len(x[0])))
    
    # Write files
    for tier, words_list in tier_words.items():
        filepath = output_dir / f"words_{tier}.txt"
        with open(filepath, 'w', encoding='utf-8') as f:
            for word, zipf in words_list:
                f.write(f"{word}\t{zipf:.2f}\n")
        print(f"{tier}: {len(words_list)} words -> {filepath}")
    
    # Also create a combined first names list
    # Common first names tend to be good OG names
    first_names = [
        "john", "james", "robert", "michael", "william", "david", "richard", "joseph",
        "thomas", "christopher", "charles", "daniel", "matthew", "anthony", "mark",
        "donald", "steven", "paul", "andrew", "joshua", "kenneth", "kevin", "brian",
        "george", "edward", "ronald", "timothy", "jason", "jeffrey", "ryan", "jacob",
        "gary", "nicholas", "eric", "jonathan", "stephen", "larry", "justin", "scott",
        "brandon", "benjamin", "samuel", "gregory", "frank", "alexander", "raymond",
        "patrick", "jack", "dennis", "jerry", "tyler", "aaron", "jose", "adam",
        "nathan", "henry", "zachary", "douglas", "peter", "kyle", "walter", "ethan",
        "jeremy", "harold", "keith", "christian", "roger", "noah", "gerald", "carl",
        "terry", "sean", "austin", "arthur", "lawrence", "jesse", "dylan", "bryan",
        "joe", "jordan", "billy", "bruce", "albert", "willie", "gabriel", "logan",
        "alan", "juan", "wayne", "roy", "ralph", "randy", "eugene", "vincent",
        "russell", "louis", "philip", "bobby", "johnny", "bradley", "mary", "patricia",
        "jennifer", "linda", "elizabeth", "barbara", "susan", "jessica", "sarah",
        "karen", "nancy", "lisa", "betty", "margaret", "sandra", "ashley", "kimberly",
        "emily", "donna", "michelle", "dorothy", "carol", "amanda", "melissa",
        "deborah", "stephanie", "rebecca", "sharon", "laura", "cynthia", "kathleen",
        "amy", "shirley", "angela", "helen", "anna", "brenda", "pamela", "nicole",
        "emma", "olivia", "ava", "isabella", "sophia", "mia", "charlotte", "amelia",
        "harper", "evelyn", "abigail", "emily", "elizabeth", "sofia", "avery", "ella"
    ]
    
    # Filter and categorize first names
    firstname_tiers = {tier: [] for tier in TIER_CRITERIA}
    for name in first_names:
        tier = categorize_word(name)
        if tier:
            zipf = get_zipf_frequency(name)
            firstname_tiers[tier].append((name, zipf))
    
    for tier in firstname_tiers:
        firstname_tiers[tier].sort(key=lambda x: (-x[1], len(x[0])))
        filepath = output_dir / f"firstnames_{tier}.txt"
        with open(filepath, 'w', encoding='utf-8') as f:
            for name, zipf in firstname_tiers[tier]:
                f.write(f"{name}\t{zipf:.2f}\n")
        print(f"firstnames_{tier}: {len(firstname_tiers[tier])} names -> {filepath}")

if __name__ == "__main__":
    main()