"""
Download all epub files from HarborLibrary GitHub repos, extract Chinese text,
save to data/books/<title>.txt (gitignored under data/).

Usage:
    python3 scripts/setup_books.py

Run once on the server. Re-run to update if repos add new books.
"""
import io
import json
import os
import re
import urllib.request
import zipfile

REPOS = [
    "HarborLibrary/Philosophy",
    "HarborLibrary/Commerce",
    "HarborLibrary/Political-Science",
    "HarborLibrary/Psychology",
]

BOOKS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "books")
GITHUB_API = "https://api.github.com/repos/{repo}/git/trees/HEAD?recursive=1"
GITHUB_RAW = "https://github.com/{repo}/raw/HEAD/{path}"


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "health-bot-setup"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _list_epubs(repo: str) -> list[str]:
    """Return list of epub paths in the repo."""
    try:
        tree = _fetch_json(GITHUB_API.format(repo=repo))
        return [
            item["path"]
            for item in tree.get("tree", [])
            if item["path"].lower().endswith(".epub")
        ]
    except Exception as e:
        print(f"  Failed to list {repo}: {e}")
        return []


def _download(repo: str, path: str) -> bytes:
    url = GITHUB_RAW.format(repo=repo, path=urllib.parse.quote(path))
    req = urllib.request.Request(url, headers={"User-Agent": "health-bot-setup"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _extract_text(epub_bytes: bytes) -> str:
    chunks = []
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        for name in sorted(zf.namelist()):
            if not name.endswith((".html", ".xhtml", ".htm")):
                continue
            raw = zf.read(name).decode("utf-8", errors="ignore")
            text = re.sub(r"<[^>]+>", "", raw)
            text = re.sub(r"[ \t]+", " ", text)
            chunks.append(text)
    full = "\n".join(chunks)
    return re.sub(r"\n{3,}", "\n\n", full)


def _safe_filename(path: str) -> str:
    """Turn epub path into a safe ascii-friendly filename."""
    name = os.path.basename(path)
    name = name.replace(".epub", "")
    # Keep Chinese chars, letters, digits, spaces
    name = re.sub(r"[^\w一-鿿\s\-]", "_", name)
    return name.strip("_- ") + ".txt"


def main() -> None:
    import urllib.parse  # noqa: F401 — needed inside _download

    os.makedirs(BOOKS_DIR, exist_ok=True)
    total = 0

    for repo in REPOS:
        print(f"\n[{repo}]")
        epubs = _list_epubs(repo)
        print(f"  Found {len(epubs)} epub(s)")

        for path in epubs:
            out_name = _safe_filename(path)
            out_path = os.path.join(BOOKS_DIR, out_name)

            if os.path.exists(out_path):
                print(f"  Skip (exists): {out_name}")
                continue

            print(f"  Downloading: {os.path.basename(path)} …", end=" ", flush=True)
            try:
                epub_bytes = _download(repo, path)
                text = _extract_text(epub_bytes)
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(text)
                print(f"{len(text):,} chars → {out_name}")
                total += 1
            except Exception as e:
                print(f"FAILED: {e}")

    print(f"\nDone. {total} new book(s) saved to {BOOKS_DIR}")


if __name__ == "__main__":
    import urllib.parse
    main()
