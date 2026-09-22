# `backloggd_top_100.json`

Input for `app/scripts/match_backloggd_top100.py`. Ships as `[]` -
deliberately empty, not pre-filled with a guessed list, since that would
misrepresent fabricated data as Backloggd's real, current Top 100.

Populate it with the current list from https://backloggd.com/games/top-100/
(that page currently blocks automated fetching - see the script's module
docstring for details) in this shape:

```json
[
  {"rank": 1, "title": "Elden Ring"},
  {"rank": 2, "title": "The Legend of Zelda: Breath of the Wild"},
  ...
]
```

Then run `python -m app.scripts.match_backloggd_top100`.
