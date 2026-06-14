import json
import random
from pathlib import Path

_QUOTES_PATH = Path(__file__).parent.parent.parent / "data" / "quotes.json"


def get_random_quote() -> dict:
    with open(_QUOTES_PATH) as f:
        quotes = json.load(f)
    return random.choice(quotes)
