import re

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"
# WeebCentral series ids are 26-char Crockford-base32 ULIDs, e.g. 01J76XY7E9FNDZ1DBBM6PBJPFK
SERIES_RE = re.compile(r"weebcentral\.com/series/([0-9A-Z]{26})/([^\"'/?]+)")


def parse_series_id(html):
    """First series result in a WeebCentral /search/simple response -> (ulid, slug)."""
    m = SERIES_RE.search(html)
    return (m.group(1), m.group(2)) if m else (None, None)


def resolve(title):
    # Quick-search htmx endpoint returns the series result list as HTML.
    r = requests.post("https://weebcentral.com/search/simple",
                      params={"location": "main"}, data={"text": title},
                      headers={"User-Agent": UA, "HX-Request": "true"}, timeout=30)
    r.raise_for_status()
    return parse_series_id(r.text)
