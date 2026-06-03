"""LLM utility functions.

Provides image compression, encoding, and content-building helpers
for preparing images to be sent to vision-capable LLM models.

Example::

    from donna.core.llm.utils import compress_image_to_base64, build_image_content

    data_url = compress_image_to_base64(raw_bytes)
    content = build_image_content(raw_bytes)
    # content = {"type": "image_url", "image_url": {"url": "data:...", "detail": "low"}}
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Any

from donna.core.logging import get_logger

logger = get_logger(__name__)

MAX_BASE64_SIZE = 400_000  # ~400 KB cap for LLM APIs

IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp", ".gif"}
)


def compress_image_to_base64(
    image_bytes: bytes,
    max_size: tuple[int, int] = (480, 480),
    quality: int = 70,
) -> str:
    """Compress image bytes and encode as a base64 JPEG data URL.

    Handles transparency (RGBA/LA/P) by compositing onto a white
    background. Resizes to fit within ``max_size`` while preserving
    aspect ratio. Outputs progressive JPEG.

    Args:
        image_bytes: Raw image bytes (any PIL-supported format).
        max_size: Maximum ``(width, height)`` for resizing. Images
            smaller than this are not upscaled.
        quality: JPEG compression quality (1-100). Lower values
            produce smaller output.

    Returns:
        Base64 data URL string (``data:image/jpeg;base64,...``).

    Raises:
        ValueError: If ``image_bytes`` is empty.
        ValueError: If the image cannot be decoded or compressed.
    """
    if not image_bytes:
        raise ValueError("image_bytes is empty")

    try:
        from PIL import Image

        image = Image.open(BytesIO(image_bytes))

        # Flatten transparency onto white background
        if image.mode in ("RGBA", "LA", "P"):
            if image.mode == "RGBA":
                background = Image.new("RGB", image.size, (255, 255, 255))
                background.paste(image, mask=image.split()[-1])
                image = background
            else:
                image = image.convert("RGB")

        # Resize if exceeds max dimensions
        if image.size[0] > max_size[0] or image.size[1] > max_size[1]:
            image.thumbnail(max_size, Image.Resampling.LANCZOS)

        # Compress to progressive JPEG
        output = BytesIO()
        image.save(
            output,
            format="JPEG",
            quality=quality,
            optimize=True,
            progressive=True,
            subsampling=2,
        )
        b64 = base64.b64encode(output.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"

    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Failed to compress image: {exc}") from exc


def build_image_content(
    image_bytes: bytes,
    max_size: tuple[int, int] = (480, 480),
    quality: int = 70,
    detail: str = "low",
    max_base64_size: int = MAX_BASE64_SIZE,
) -> dict[str, Any]:
    """Build an OpenAI-compatible image content dict from raw bytes.

    Compresses the image, validates size constraints, and returns a
    dict ready to be included in an LLM messages array.

    Args:
        image_bytes: Raw image bytes (any PIL-supported format).
        max_size: Maximum ``(width, height)`` for resizing.
        quality: JPEG compression quality (1-100).
        detail: OpenAI vision detail level (``"low"``, ``"high"``,
            or ``"auto"``).
        max_base64_size: Maximum base64 string length. Images
            exceeding this after compression are rejected.

    Returns:
        Dict with ``type`` and ``image_url`` keys, compatible with
        OpenAI/LiteLLM vision message format::

            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/jpeg;base64,...",
                    "detail": "low",
                },
            }

    Raises:
        ValueError: If image_bytes is empty, cannot be compressed,
            or exceeds ``max_base64_size`` after compression.
    """
    data_url = compress_image_to_base64(
        image_bytes,
        max_size=max_size,
        quality=quality,
    )

    # Validate size after compression
    base64_part = data_url.split(",", 1)[1] if "," in data_url else data_url
    if len(base64_part) > max_base64_size:
        raise ValueError(
            f"Image too large after compression "
            f"({len(base64_part)} chars, max {max_base64_size})"
        )

    return {
        "type": "image_url",
        "image_url": {
            "url": data_url,
            "detail": detail,
        },
    }


def file_to_image_content(
    file_path: Path | str,
    max_size: tuple[int, int] = (480, 480),
    quality: int = 70,
    detail: str = "low",
) -> dict[str, Any]:
    """Build an image content dict from a file path.

    Convenience wrapper around ``build_image_content`` that reads
    the file from disk.

    Args:
        file_path: Path to an image file.
        max_size: Maximum ``(width, height)`` for resizing.
        quality: JPEG compression quality (1-100).
        detail: OpenAI vision detail level.

    Returns:
        Image content dict for LLM vision messages.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is not a supported image format,
            or image processing fails.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"File {file_path} does not exist")

    if file_path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(f"Not a supported image format: {file_path.suffix}")

    return build_image_content(
        file_path.read_bytes(),
        max_size=max_size,
        quality=quality,
        detail=detail,
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m donna.core.llm.utils <image_path>")
        sys.exit(1)

    path = Path(sys.argv[1])
    raw = path.read_bytes()

    print(f"File: {path}")
    print(f"Raw size: {len(raw):,} bytes")

    data_url = compress_image_to_base64(raw)
    b64_part = data_url.split(",", 1)[1]
    print(f"Compressed base64 size: {len(b64_part):,} chars")

    content = build_image_content(raw)
    print(f"Content dict detail: {content['image_url']['detail']}")
    print("Ready for LLM vision input.")
