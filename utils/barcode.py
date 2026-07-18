"""Decode a product barcode (EAN/UPC) from a photo, using the bundled
zxing-cpp wheel (no system libs). Returns the digit string, or None."""
import io
import logging

logger = logging.getLogger(__name__)

_VALID_LENS = {8, 12, 13, 14}  # EAN-8, UPC-A, EAN-13, GTIN-14


def decode(image_bytes: bytes) -> str | None:
    """Return the first plausible product barcode in the image, or None.

    Tries the image as-is, then a 2x upscale (helps small/blurry phone shots).
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

    for scale in (1, 2):
        candidate = img
        if scale != 1:
            candidate = img.resize((img.width * scale, img.height * scale))
        try:
            results = zxingcpp.read_barcodes(candidate)
        except Exception:
            logger.exception("zxingcpp read failed")
            results = []
        # prefer a clean product code (all digits, standard length)
        for r in results:
            text = (r.text or "").strip()
            if text.isdigit() and len(text) in _VALID_LENS:
                return text
        # otherwise accept whatever decoded on the first pass
        if scale == 1 and results:
            text = (results[0].text or "").strip()
            if text:
                return text
    return None
