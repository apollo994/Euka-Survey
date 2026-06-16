"""Wikipedia summary lookup for the root taxon's "About" card.

A single lightweight GET against Wikipedia's REST summary endpoint, which
returns a short JSON (description + first-paragraph extract + thumbnail
URL) and transparently follows redirects — so NCBI scientific names like
"Metazoa" or "Viridiplantae" resolve to the "Animal"/"Viridiplantae"
articles without us maintaining a name map.

Cached per name via `@st.cache_data` (24h TTL), so there's at most one
request per unique root taxon and no meaningful memory cost. Failures
(network, 404, disambiguation, no extract) return `None` and the caller
simply omits the card — it's decorative, never load-bearing.
"""

import logging
import urllib.parse

import requests
import streamlit as st

log = logging.getLogger("euka.wikipedia")

_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
_TIMEOUT_SECONDS = 6
# Wikipedia's API policy requires a descriptive User-Agent; requests
# without one can be rejected with HTTP 403.
_HEADERS = {
    "User-Agent": "EukaSurvey/1.0 (https://github.com/Cobos-Bioinfo/Euka-Survey)",
}


@st.cache_data(ttl=86_400, show_spinner=False)
def get_taxon_summary(name: str) -> dict | None:
    """Return `{title, description, extract, thumbnail, url}` for `name`,
    or `None` if there's no usable summary."""
    if not name or name in {"Unknown", "Error"}:
        return None

    url = _SUMMARY_URL.format(title=urllib.parse.quote(name))
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            return None
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        log.info("Wikipedia summary lookup failed for %r: %s", name, e)
        return None

    # Skip disambiguation pages and entries with no real summary text.
    if data.get("type") == "disambiguation" or not data.get("extract"):
        return None

    content_urls = data.get("content_urls") or {}
    desktop = content_urls.get("desktop") or {}
    return {
        "title": data.get("title") or name,
        "description": data.get("description") or "",
        "extract": data.get("extract") or "",
        "thumbnail": (data.get("thumbnail") or {}).get("source"),
        "url": desktop.get("page") or f"https://en.wikipedia.org/wiki/{urllib.parse.quote(name)}",
    }
