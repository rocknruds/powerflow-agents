"""URL fetching and clean text extraction for the ingestion agent."""

import requests
from bs4 import BeautifulSoup
from rich.console import Console

console = Console()

# Tags that typically contain boilerplate/navigation content to remove
_NOISE_TAGS = [
    "nav", "header", "footer", "aside", "script", "style",
    "noscript", "form", "button", "advertisement", "figure",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_url(url: str, timeout: int = 15) -> str:
    """Fetch a URL and return clean article text.

    Raises RuntimeError if the page cannot be fetched or parsed.
    """
    try:
        response = requests.get(url, headers=_HEADERS, timeout=timeout)
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        raise RuntimeError(
            f"HTTP {exc.response.status_code} fetching {url}: {exc}"
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError(f"Could not connect to {url}: {exc}") from exc
    except requests.exceptions.Timeout as exc:
        raise RuntimeError(f"Request timed out after {timeout}s for {url}") from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        raise RuntimeError(
            f"URL returned non-HTML content ({content_type}). "
            "This may be a PDF, paywall, or JS-rendered page."
        )

    return _extract_text(response.text, url)


def _extract_text(html: str, url: str) -> str:
    """Parse HTML and return clean article text."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(tags := _NOISE_TAGS):
        for element in soup.find_all(tag):
            element.decompose()

    # Prefer semantic article containers
    article = (
        soup.find("article")
        or soup.find("main")
        or soup.find(id="content")
        or soup.find(id="main-content")
        or soup.find(class_="article-body")
        or soup.find(class_="post-content")
        or soup.find(class_="entry-content")
        or soup.body
    )

    if article is None:
        raise RuntimeError(f"Could not locate article body in {url}")

    lines = []
    for element in article.find_all(["p", "h1", "h2", "h3", "h4", "li", "blockquote"]):
        text = element.get_text(separator=" ", strip=True)
        if len(text) > 40:  # skip very short fragments (captions, labels)
            lines.append(text)

    text = "\n\n".join(lines)

    if len(text) < 200:
        raise RuntimeError(
            f"Extracted text is too short ({len(text)} chars). "
            "The page may be paywalled, JS-rendered, or structured unusually."
        )

    return text
