"""The canonical command list. /help renders it, and each command's description is taken
from it, so the two can never drift apart.

Keep this module free of imports from the command modules, because views.py imports it.
"""

COMMANDS = [
    ("help", "What this is, every command, and links to the web app and donations"),
    ("search", "Search words, idioms and names"),
    ("random", "A random entry"),
    ("wotd", "The word of the day, the same one for everybody"),
    ("favs", "Your saved entries"),
    ("sub", "Get the word of the day every day, by DM or in a server channel"),
    ("unsub", "Stop the daily word"),
    ("settings", "Timezone, delivery hour, and whether a quote is attached"),
    ("stats", "Catalogue sizes and the newest entry"),
    ("privacy", "Exactly what is stored, and a button to erase it"),
]

DESCRIPTIONS = dict(COMMANDS)
