"""Decode a product barcode (EAN/UPC) from a photo, using the bundled
zxing-cpp wheel (no system libs). Returns the digit string, or None."""
import io
import logging
import time

logger = logging.getLogger(__name__)

_VALID_LENS = {8, 12, 13, 14}  # EAN-8, UPC-A, EAN-13, GTIN-14
_SCAN_EDGE = 1600  # long edge for the first pass


def decode(image_bytes: bytes) -> str | None:
    """Return the first plausible product barcode in the image, or None.

    A 12 MP phone shot scans about ten times faster downscaled and finds the same
    code, so that is tried first. Upscaling is kept only for an image that is
    genuinely small, where it can add something.
    """
    try:
        import zxingcpp
        from PIL import Image
    except Exception:
        logger.exception("barcode deps missing")
        return None

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        logger.exception("cannot open barcode image")
        return None

    started = time.perf_counter()
    fallback = None
    for candidate in _passes(img):
        try:
            results = zxingcpp.read_barcodes(candidate)
        except Exception:
            logger.exception("zxingcpp read failed")
            continue
        # prefer a clean product code (all digits, standard length)
        for r in results:
            text = (r.text or "").strip()
            if text.isdigit() and len(text) in _VALID_LENS:
                logger.info("barcode %s in %.2fs (%dx%d)", text,
                            time.perf_counter() - started, *candidate.size)
                return text
        if fallback is None and results:
            fallback = (results[0].text or "").strip() or None

    logger.info("barcode %s in %.2fs", fallback or "not found",
                time.perf_counter() - started)
    return fallback


def _passes(img):
    """Cheapest pass first, so the common case never pays for the expensive ones."""
    long_edge = max(img.size)
    if long_edge > _SCAN_EDGE:
        small = img.copy()
        small.thumbnail((_SCAN_EDGE, _SCAN_EDGE))
        yield small
    yield img
    if long_edge < 800:
        yield img.resize((img.width * 2, img.height * 2))
