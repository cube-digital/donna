"""Vision LLM document extraction.

Uses a multimodal vision model via :class:`~donna.core.llm.factory.LLMFactory`
to extract text from images and PDFs. PDF pages are rasterised to PNG
using ``pdf2image`` (requires poppler).

This is the most expensive strategy and should be last in the fallback
order. The LLM naturally returns markdown — HTML is generated via
``markdown_to_html()`` from ``donna.core.ocr.utils``.
"""

from __future__ import annotations

import base64
import time
from io import BytesIO
from pathlib import Path
from typing import Any

from donna.core.llm.factory import LLMFactory
from donna.core.logging import get_logger
from donna.core.ocr.base import OCRResult
from donna.core.ocr.utils import markdown_to_html

logger = get_logger(__name__)

IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp", ".gif"}
)

# Map of file extensions to image media types accepted natively by
# vision providers. Extensions absent from this map (e.g. ``.tiff``,
# ``.bmp``) are transcoded to PNG before sending — Anthropic rejects
# the request when the declared media type does not match the actual
# image bytes, and only supports jpeg/png/gif/webp.
_NATIVE_MIME_BY_SUFFIX: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

DEFAULT_PROMPT = (
    "Extract the complete text content from this document. "
    "Preserve the document structure: headings, paragraphs, lists, tables. "
    "Output as clean markdown. Do not summarize or omit content."
)


def _encode_image_for_vision(image_bytes: bytes, suffix: str) -> tuple[str, str]:
    """Return ``(base64, mime_type)`` for raw image bytes.

    Bytes are passed through unchanged when the extension maps to a
    natively supported media type. Otherwise the image is decoded with
    PIL and re-encoded as PNG so the declared media type matches the
    actual content (Anthropic enforces this strictly).
    """
    suffix = suffix.lower()
    native_mime = _NATIVE_MIME_BY_SUFFIX.get(suffix)
    if native_mime is not None:
        return base64.b64encode(image_bytes).decode(), native_mime

    from io import BytesIO

    from PIL import Image

    with Image.open(BytesIO(image_bytes)) as img:
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGB")
        out = BytesIO()
        img.save(out, format="PNG")
        return base64.b64encode(out.getvalue()).decode(), "image/png"


class LLMStrategy:
    """Vision-based document extraction using a multimodal chat model.

    Renders document pages to images and sends them to a vision model
    for text extraction. Satisfies the ``OCRStrategy`` Protocol.

    For bytes or PIL image input, use the facade's ``extract_from_bytes``
    and ``extract_from_image`` convenience methods instead.

    Attributes:
        model: The LLM model name (e.g. ``"gpt-4o-mini"``).
        kwargs: Additional keyword arguments passed to ``LLMFactory.create()``.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        prompt: str | None = None,
        enhance_images: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialise the LLM strategy.

        Args:
            model: Vision-capable model name compatible with ``LLMFactory``.
            prompt: Custom extraction prompt. ``None`` uses the default
                prompt that requests clean markdown with preserved structure.
            enhance_images: Apply OpenCV preprocessing (deskew, denoise,
                contrast, sharpen) before sending to the LLM. Useful for
                faded or noisy scans. No effect on clean scans.
            **kwargs: Additional keyword arguments forwarded to
                ``LLMFactory.create()``.
        """
        self.model = model
        self._prompt = prompt
        self._enhance_images = enhance_images
        self.kwargs = kwargs

    def extract(self, file_path: Path) -> OCRResult:
        """Extract text from an image or PDF using LLM vision.

        Images are encoded directly as base64. PDFs are rasterised
        page-by-page to PNG using ``pdf2image`` (capped at ``max_pages``).

        Args:
            file_path: Path to the image or PDF file.

        Returns:
            ``OCRResult`` with markdown text, converted HTML, page count,
            and usage metadata (model name, token counts).

        Raises:
            ValueError: If the file type is not an image or PDF.
        """
        file_path = Path(file_path)
        start = time.perf_counter()
        suffix = file_path.suffix.lower()

        if suffix in IMAGE_EXTENSIONS:
            if self._enhance_images:
                import cv2

                from donna.core.ocr.image_enhancement import enhance_for_ocr

                img_array = cv2.imread(str(file_path))
                img_array = enhance_for_ocr(img_array)
                _, png_bytes = cv2.imencode(".png", img_array)
                images = [(base64.b64encode(png_bytes.tobytes()).decode(), "image/png")]
            else:
                images = [_encode_image_for_vision(file_path.read_bytes(), suffix)]
            page_count = 1
        elif suffix == ".pdf":
            images_b64, page_count = self._pdf_to_images(file_path)
            images = [(b64, "image/png") for b64 in images_b64]
        else:
            raise ValueError(f"LLM strategy cannot process {suffix} files")

        prompt = self._prompt or DEFAULT_PROMPT
        md_text, usage = self._vision_markdown(images, prompt)
        html = markdown_to_html(md_text)
        duration = time.perf_counter() - start

        return OCRResult(
            text=md_text,
            html=html,
            provider="llm",
            page_count=page_count,
            metadata={"model": self.model, "usage": usage},
            duration_seconds=duration,
        )

    def _vision_markdown(
        self,
        images: list[tuple[str, str]],
        prompt: str,
    ) -> tuple[str, dict[str, Any] | None]:
        """Send images to the vision model and return extracted text.

        Builds a single multimodal user message containing the prompt
        and all images, then calls the model via ``LLMFactory``.

        Args:
            images: List of ``(base64_data, media_type)`` tuples — e.g.
                ``("…", "image/jpeg")``. Anthropic rejects mismatched
                media types so the caller is responsible for getting it
                right.
            prompt: Extraction prompt text.

        Returns:
            Tuple of ``(markdown_text, usage_dict)``. Usage may be
            ``None`` if the provider does not report it.
        """
        provider = LLMFactory.create(model=self.model, **self.kwargs)
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for b64, mime in images:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                }
            )

        response = provider.chat(
            messages=[{"role": "user", "content": content}],
            temperature=0.1,
        )
        raw = response.content
        text = raw if isinstance(raw, str) else str(raw)
        usage = getattr(response, "usage", None)
        if usage is not None and hasattr(usage, "model_dump"):
            usage = usage.model_dump()
        elif usage is not None and not isinstance(usage, dict):
            usage = dict(usage) if usage else None
        return text, usage

    def _pdf_to_images(
        self,
        pdf_path: Path,
        max_pages: int = 20,
        max_edge_px: int = 3000,
    ) -> tuple[list[str], int]:
        """Rasterise PDF pages to base64 PNG strings using pdf2image.

        Args:
            pdf_path: Path to the PDF file.
            max_pages: Maximum number of pages to rasterise.
            max_edge_px: Longest output edge in pixels. Using a size cap
                instead of a fixed DPI keeps phone-scan PDFs (whose page
                boxes can be 3024×4032 pt or larger) from exploding into
                multi-hundred-MB rasters — rendering them at 300 DPI
                would OOM the worker.

        Returns:
            Tuple of ``(base64_images, total_page_count)``.
        """
        from pdf2image import convert_from_path, pdfinfo_from_path

        info = pdfinfo_from_path(str(pdf_path))
        total_pages = info.get("Pages", 0)

        pil_images = convert_from_path(
            str(pdf_path),
            size=max_edge_px,
            last_page=min(total_pages, max_pages),
        )

        images: list[str] = []
        for img in pil_images:
            if self._enhance_images:
                import cv2
                import numpy as np

                from donna.core.ocr.image_enhancement import enhance_for_ocr

                # PIL → numpy (RGB→BGR for OpenCV)
                img_array = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                img_array = enhance_for_ocr(img_array)
                _, png_bytes = cv2.imencode(".png", img_array)
                images.append(base64.b64encode(png_bytes.tobytes()).decode())
            else:
                buf = BytesIO()
                img.save(buf, format="PNG")
                images.append(base64.b64encode(buf.getvalue()).decode())

        return images, total_pages


if __name__ == "__main__":
    import sys

    DEFAULT_TEST_PDF = (
        "data/test/544-108-2022 - Aeroportul vs CJ pretentii fond/"
        "108 544-108-2022 Raport de expertiză 14_05_2024.pdf"
    )

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_TEST_PDF)
    print(f"{'=' * 60}")
    print("LLM OCR Strategy Test")
    print(f"{'=' * 60}")
    print(f"File: {path}")
    print(f"Exists: {path.exists()}")
    print()

    strategy = LLMStrategy(model="gpt-4o")
    result = strategy.extract(path)
    print(f"Provider: {result.provider}")
    print(f"Pages: {result.page_count}")
    print(f"Title: {result.title}")
    print(f"Text length: {len(result.text)} chars")
    print(f"HTML length: {len(result.html or '')} chars")
    print(f"Is valid: {result.is_valid}")
    print(f"Model: {result.metadata.get('model')}")
    print(f"Usage: {result.metadata.get('usage')}")
    print(f"Duration: {result.duration_seconds:.3f}s")
    print()
    print("--- First 500 chars of text ---")
    print(result.text[:500])
    print(f"{'=' * 60}")

