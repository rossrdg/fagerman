"""Small helpers for the news (blog) feature: slugs, YouTube links, HTML cleaning."""
import html
import re
from urllib.parse import quote, urlparse

import bleach

# --- Slugs -----------------------------------------------------------------
# Bulgarian -> Latin ("Streamlined System"), so /news/stazh-v-borussia-dortmund
# looks fine when shared on Facebook.
_BG = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sht", "ъ": "a",
    "ь": "y", "ю": "yu", "я": "ya",
}


def slugify(text, max_len=80):
    out = "".join(_BG.get(ch, ch) for ch in (text or "").lower())
    out = re.sub(r"[^a-z0-9]+", "-", out).strip("-")
    return out[:max_len].strip("-")


# --- YouTube ---------------------------------------------------------------
_YT_ID = r"[A-Za-z0-9_-]{11}"
_YT_PATTERNS = [
    re.compile(rf"^https?://(?:www\.|m\.)?youtube\.com/watch\?(?:[^#]*&)?v=({_YT_ID})(?:[&#]|$)"),
    re.compile(rf"^https?://youtu\.be/({_YT_ID})(?:[/?#]|$)"),
    re.compile(rf"^https?://(?:www\.|m\.)?youtube\.com/(?:shorts|embed|live)/({_YT_ID})(?:[/?#]|$)"),
]


def extract_youtube_id(url):
    """Returns the 11-char video id from a YouTube link, or None."""
    url = (url or "").strip()
    for pattern in _YT_PATTERNS:
        m = pattern.match(url)
        if m:
            return m.group(1)
    return None


# --- Facebook posts --------------------------------------------------------
_FB_HOSTS = {"facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com", "fb.watch"}


def clean_facebook_url(url):
    """Returns the link if it looks like a link to a Facebook post/video, else None."""
    url = (url or "").strip()
    if not url or len(url) > 500:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in _FB_HOSTS:
        return None
    if not parsed.path.strip("/") and not parsed.query:  # just the homepage
        return None
    return url


def facebook_embed_src(url):
    """Address of Facebook's official embed (works only for public posts)."""
    if not url:
        return None
    return ("https://www.facebook.com/plugins/post.php?href=" + quote(url, safe="")
            + "&show_text=true&width=500")


# --- HTML from the editor --------------------------------------------------
ALLOWED_TAGS = [
    "p", "br", "strong", "b", "em", "i", "u", "s",
    "h2", "h3", "ul", "ol", "li", "blockquote", "a", "img",
]
ALLOWED_ATTRS = {"a": ["href", "title"], "img": ["src", "alt"]}
ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def sanitize_html(raw):
    """Keeps only the formatting the editor offers; scripts, event handlers,
    styles and unknown tags are removed. Emoji (plain Unicode) are untouched."""
    return bleach.clean(
        raw or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    ).strip()


def plain_text(html_text):
    text = re.sub(r"<[^>]+>", " ", html_text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def make_excerpt(html_text, limit=160):
    text = plain_text(html_text)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(".,;:!? ") + "…"
