"""
Run once on the server to download Zarathustra epub and extract quotes.
Output: data/zarathustra_quotes.txt  (one quote per line, gitignored)

Usage:
    python scripts/setup_quotes.py
"""
import os
import re
import zipfile
import urllib.request
import io

EPUB_URL = (
    "https://github.com/HarborLibrary/Philosophy/raw/master/"
    "%E5%BC%97%E9%87%8C%E5%BE%B7%E9%87%8C%E5%B8%8C%C2%B7%E5%B0%BC%E9%87%87%EF%BC%9A"
    "%E6%9F%A5%E6%8B%89%E5%9B%BE%E6%96%AF%E7%89%B9%E6%8B%89%E5%A6%82%E6%98%AF%E8%AF%B4.epub"
)

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "zarathustra_quotes.txt"
)
FULL_TEXT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "zarathustra_full.txt"
)

# Minimum / maximum char length for a quote candidate
MIN_LEN = 15
MAX_LEN = 120


def _extract_text_from_epub(epub_bytes: bytes) -> str:
    """Pull all text out of the epub (which is a ZIP of HTML files)."""
    chunks = []
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        for name in sorted(zf.namelist()):
            if not name.endswith((".html", ".xhtml", ".htm")):
                continue
            raw = zf.read(name).decode("utf-8", errors="ignore")
            # Strip tags
            text = re.sub(r"<[^>]+>", "", raw)
            # Collapse whitespace
            text = re.sub(r"[ \t]+", " ", text)
            chunks.append(text)
    return "\n".join(chunks)


def _extract_quotes(full_text: str) -> list[str]:
    """
    Split text into sentence-like segments and keep those that look
    like meaningful philosophical statements.
    """
    # Split on Chinese sentence-ending punctuation
    segments = re.split(r"[。！？；\n]", full_text)

    seen = set()
    quotes = []
    for seg in segments:
        seg = seg.strip()
        # Remove leading chapter numbers / decorative chars
        seg = re.sub(r"^[\d\s　　一二三四五六七八九十百第章节]+[、．.]*\s*", "", seg)
        seg = seg.strip("「」『』《》〈〉【】—…·•※★○●▲△■□◆◇☆*")
        seg = seg.strip()

        if len(seg) < MIN_LEN or len(seg) > MAX_LEN:
            continue
        # Must contain at least a few Chinese characters
        if len(re.findall(r"[一-鿿]", seg)) < 8:
            continue
        # Skip pure narration/dialogue markers
        if seg.startswith(("于是", "然后", "他说", "她说", "查拉图斯特拉说")):
            continue
        # Deduplicate
        key = re.sub(r"\s+", "", seg)
        if key in seen:
            continue
        seen.add(key)
        quotes.append(seg)

    return quotes


def main() -> None:
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    print(f"Downloading epub from GitHub …")
    with urllib.request.urlopen(EPUB_URL, timeout=30) as resp:
        epub_bytes = resp.read()
    print(f"Downloaded {len(epub_bytes):,} bytes")

    full_text = _extract_text_from_epub(epub_bytes)
    print(f"Extracted {len(full_text):,} chars of text")

    quotes = _extract_quotes(full_text)
    print(f"Found {len(quotes)} quote candidates")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for q in quotes:
            f.write(q + "\n")
    print(f"Saved quotes to {OUTPUT_PATH}")

    # Save cleaned full text for grep-based search
    # Collapse excessive blank lines to keep file compact
    clean = re.sub(r"\n{3,}", "\n\n", full_text)
    with open(FULL_TEXT_PATH, "w", encoding="utf-8") as f:
        f.write(clean)
    print(f"Saved full text to {FULL_TEXT_PATH} ({len(clean):,} chars)")


if __name__ == "__main__":
    main()
