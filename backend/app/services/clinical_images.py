"""Decode clinical photos to bounded, metadata-free JPEGs."""

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
FORMATS = ("JPEG", "PNG", "WEBP")


def sanitize_photo(raw: bytes) -> tuple[bytes, bytes]:
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("Choose a JPEG, PNG or WebP image under 8 MB")
    try:
        with Image.open(BytesIO(raw), formats=FORMATS) as opened:
            width, height = opened.size
            if min(width, height) < 16 or width * height > MAX_IMAGE_PIXELS:
                raise ValueError("Unsupported image dimensions")
            if getattr(opened, "n_frames", 1) != 1:
                raise ValueError("Choose a single still image")
            opened.load()
            oriented = ImageOps.exif_transpose(opened)
            # Paste on a new canvas so no source metadata can survive re-encoding.
            clean = Image.new("RGB", oriented.size, "white")
            rgb = oriented.convert("RGBA")
            clean.paste(rgb, mask=rgb.getchannel("A"))
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise ValueError("Choose a valid JPEG, PNG or WebP image") from None
    clean.thumbnail((2400, 2400))
    full = BytesIO()
    clean.save(full, format="JPEG", quality=88)
    clean.thumbnail((320, 320))
    thumbnail = BytesIO()
    clean.save(thumbnail, format="JPEG", quality=82)
    return full.getvalue(), thumbnail.getvalue()


def image_path(owner: str, patient: str, case: str, image: str, variant: str) -> str:
    return f"{owner}/{patient}/{case}/{image}/{variant}.jpg"
