"""Image enhancement for OCR — STUB.

Placeholder module for OpenCV-based preprocessing (deskew, denoise,
contrast, sharpen) used by ``LLMStrategy(enhance_images=True)``. The
real implementation is deferred; this stub keeps the import resolvable
but fails loud when invoked so callers learn the feature is dormant.

To enable later: install OpenCV (``opencv-python-headless``) and
replace ``enhance_for_ocr`` with the actual pipeline.
"""

from __future__ import annotations


def enhance_for_ocr(img):  # noqa: ANN001
    """Raise NotImplementedError. Replace with real pipeline when enabling.

    Args:
        img: NumPy/cv2 image array.

    Raises:
        NotImplementedError: Always — the enhance_images feature is dormant.
    """
    raise NotImplementedError(
        "donna.core.ocr.image_enhancement.enhance_for_ocr is a stub. "
        "Pass enhance_images=False (default) until an OpenCV pipeline lands."
    )
