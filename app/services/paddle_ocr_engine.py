"""PaddleOCR text extraction for receipt/bill images."""
from __future__ import annotations

import logging
import os
import re
import threading
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


_engine_lock = threading.Lock()
_engine = None

# Upscale small / blurry phone photos before OCR (helps faint thermal print).
_MIN_OCR_WIDTH = int(os.getenv("PADDLE_OCR_MIN_WIDTH", "1400"))
_BLUR_LAPLACIAN_THRESHOLD = _env_float("PADDLE_OCR_BLUR_THRESHOLD", 120.0)
_OCR_FAST_MODE = lambda: _env_bool("PADDLE_OCR_FAST_MODE", True)
_OCR_MAX_PASSES_CLEAR = int(os.getenv("PADDLE_OCR_MAX_PASSES_CLEAR", "4"))
_OCR_MAX_PASSES_BLURRY = int(os.getenv("PADDLE_OCR_MAX_PASSES_BLURRY", "7"))


def _get_engine():
    """Lazy singleton — PaddleOCR model load is expensive."""
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        from paddleocr import PaddleOCR

        lang = os.getenv("PADDLE_OCR_LANG", "en")
        use_gpu = _env_bool("PADDLE_OCR_USE_GPU", False)
        use_angle_cls = _env_bool("PADDLE_OCR_USE_ANGLE_CLS", True)

        _engine = PaddleOCR(
            use_angle_cls=use_angle_cls,
            lang=lang,
            use_gpu=use_gpu,
            show_log=False,
            enable_mkldnn=False,
        )
        logger.info("paddle_ocr.initialized lang=%s use_gpu=%s", lang, use_gpu)
        return _engine


def _bbox_sort_key(entry) -> Tuple[float, float]:
    """Top-to-bottom, then left-to-right reading order for receipt headers."""
    try:
        box = entry[0]
        ys = [float(p[1]) for p in box]
        xs = [float(p[0]) for p in box]
        y_top = min(ys)
        x_left = min(xs)
        return (round(y_top / 12), x_left)
    except (TypeError, ValueError, IndexError):
        return (0.0, 0.0)


def _result_to_text(ocr_result) -> Tuple[str, float]:
    """Convert PaddleOCR output to plain text and mean line confidence."""
    if not ocr_result:
        return "", 0.0

    page = ocr_result[0] if isinstance(ocr_result[0], list) else ocr_result
    if not page:
        return "", 0.0

    sorted_page = sorted(
        (e for e in page if e and len(e) >= 2),
        key=_bbox_sort_key,
    )

    lines: List[str] = []
    confidences: List[float] = []
    for entry in sorted_page:
        text_conf = entry[1]
        if not text_conf:
            continue
        text = str(text_conf[0]).strip()
        if not text:
            continue
        lines.append(text)
        try:
            confidences.append(float(text_conf[1]))
        except (TypeError, ValueError):
            confidences.append(0.0)

    if not lines:
        return "", 0.0
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return "\n".join(lines), avg_conf


def _read_image_bgr(image_path: str) -> Optional[np.ndarray]:
    try:
        import cv2

        image = cv2.imread(image_path)
        return image
    except Exception:
        logger.debug("paddle_ocr.cv2_read_failed path=%s", image_path, exc_info=True)
        return None


def _pil_to_bgr(image_path: str) -> Optional[np.ndarray]:
    try:
        import cv2
        from PIL import Image

        with Image.open(image_path) as img:
            rgb = np.array(img.convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    except Exception:
        logger.debug("paddle_ocr.pil_read_failed path=%s", image_path, exc_info=True)
        return None


def _laplacian_variance(gray: np.ndarray) -> float:
    import cv2

    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _is_blurry(gray: np.ndarray) -> bool:
    return _laplacian_variance(gray) < _BLUR_LAPLACIAN_THRESHOLD


def measure_image_quality(image_path: str) -> dict:
    """Sharpness metrics for blur-aware OCR quality checks."""
    import cv2

    original = _read_image_bgr(image_path)
    if original is None:
        original = _pil_to_bgr(image_path)
    if original is None:
        return {
            "blurry": True,
            "laplacian_variance": 0.0,
            "readable": False,
        }
    original = _ensure_min_width(original)
    gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    lap = _laplacian_variance(gray)
    blurry = lap < _BLUR_LAPLACIAN_THRESHOLD
    return {
        "blurry": blurry,
        "laplacian_variance": round(lap, 2),
        "readable": not blurry,
    }


def _upscale_bgr(image: np.ndarray, factor: float) -> np.ndarray:
    import cv2

    if factor <= 1.01:
        return image
    h, w = image.shape[:2]
    return cv2.resize(
        image,
        (max(1, int(w * factor)), max(1, int(h * factor))),
        interpolation=cv2.INTER_CUBIC,
    )


def _ensure_min_width(image: np.ndarray, min_width: int = _MIN_OCR_WIDTH) -> np.ndarray:
    import cv2

    h, w = image.shape[:2]
    if w >= min_width:
        return image
    factor = min_width / max(w, 1)
    return cv2.resize(
        image,
        (int(w * factor), int(h * factor)),
        interpolation=cv2.INTER_CUBIC,
    )


def _unsharp_mask(gray: np.ndarray) -> np.ndarray:
    import cv2

    blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=2.0)
    sharp = cv2.addWeighted(gray, 1.65, blurred, -0.65, 0)
    return np.clip(sharp, 0, 255).astype(np.uint8)


def _normalize_line_key(line: str) -> str:
    key = re.sub(r"\s+", " ", line.strip().lower())
    key = key.replace("₹", "").replace("rs.", "").replace("rs", "")
    key = re.sub(r"[^\w\s%.]", "", key)
    return key


def merge_variant_texts(texts: List[str]) -> str:
    """
    Fuse OCR from multiple preprocessing passes.
    Keeps the clearest version of each line and preserves reading order.
    """
    cleaned = [t.strip() for t in texts if t and t.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]

    line_best: dict[str, str] = {}
    for text in cleaned:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            key = _normalize_line_key(stripped)
            if not key:
                continue
            prev = line_best.get(key)
            if prev is None or len(stripped) > len(prev):
                line_best[key] = stripped

    anchor = max(cleaned, key=len)
    ordered: List[str] = []
    seen: set[str] = set()
    for line in anchor.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        key = _normalize_line_key(stripped)
        if key in line_best and key not in seen:
            ordered.append(line_best[key])
            seen.add(key)

    for key, value in line_best.items():
        if key not in seen:
            ordered.append(value)
            seen.add(key)

    return "\n".join(ordered)


def _preprocess_variants(image_path: str) -> List[np.ndarray]:
    """Blur-aware preprocessing — upscale, sharpen, threshold, and denoise."""
    variants: List[np.ndarray] = []
    seen: set[int] = set()
    fast_mode = _OCR_FAST_MODE()

    original = _read_image_bgr(image_path)
    if original is None:
        original = _pil_to_bgr(image_path)
    if original is None:
        return variants

    import cv2

    original = _ensure_min_width(original)
    gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    blurry = _is_blurry(gray)
    max_variants = (
        _OCR_MAX_PASSES_BLURRY if blurry else _OCR_MAX_PASSES_CLEAR
    )
    if not fast_mode:
        max_variants = 99

    def _add(arr: Optional[np.ndarray]) -> None:
        if arr is None or arr.size == 0 or len(variants) >= max_variants:
            return
        key = int(arr.__array_interface__["data"][0])
        if key in seen:
            return
        seen.add(key)
        variants.append(arr)

    _add(original)

    if fast_mode and not blurry:
        up = _upscale_bgr(original, 1.25)
        _add(up)
        up_gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
        sharp = _unsharp_mask(up_gray)
        _add(cv2.cvtColor(sharp, cv2.COLOR_GRAY2BGR))
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        _add(cv2.cvtColor(clahe.apply(up_gray), cv2.COLOR_GRAY2BGR))
        if len(variants) < max_variants:
            try:
                from PIL import Image, ImageEnhance, ImageOps

                with Image.open(image_path) as img:
                    rgb = ImageOps.autocontrast(img.convert("RGB"))
                    rgb = ImageEnhance.Sharpness(rgb).enhance(1.4)
                    arr = np.array(ImageOps.grayscale(rgb))
                _add(cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR))
            except Exception:
                pass
        logger.debug(
            "paddle_ocr.fast_preprocess path=%s variants=%d blurry=%s",
            image_path,
            len(variants),
            blurry,
        )
        return variants

    upscale_factors = (2.2, 1.75, 1.4) if blurry else (1.5, 1.25)

    for factor in upscale_factors:
        if len(variants) >= max_variants:
            break
        up = _upscale_bgr(original, factor)
        _add(up)
        up_gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
        sharp = _unsharp_mask(up_gray)
        _add(cv2.cvtColor(sharp, cv2.COLOR_GRAY2BGR))

        clahe = cv2.createCLAHE(clipLimit=3.0 if blurry else 2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(up_gray)
        _add(cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR))

        denoised = cv2.fastNlMeansDenoising(
            up_gray, None, h=12 if blurry else 8, templateWindowSize=7, searchWindowSize=21
        )
        _add(cv2.cvtColor(denoised, cv2.COLOR_GRAY2BGR))

        bilateral = cv2.bilateralFilter(up_gray, d=9, sigmaColor=75, sigmaSpace=75)
        _add(cv2.cvtColor(bilateral, cv2.COLOR_GRAY2BGR))

        adaptive = cv2.adaptiveThreshold(
            denoised,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11,
        )
        _add(cv2.cvtColor(adaptive, cv2.COLOR_GRAY2BGR))

        _, otsu = cv2.threshold(
            denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        _add(cv2.cvtColor(otsu, cv2.COLOR_GRAY2BGR))

    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps

        with Image.open(image_path) as img:
            rgb = img.convert("RGB")
            if blurry:
                w, h = rgb.size
                rgb = rgb.resize((int(w * 1.8), int(h * 1.8)), Image.Resampling.LANCZOS)
            rgb = ImageOps.autocontrast(rgb)
            rgb = ImageEnhance.Contrast(rgb).enhance(1.35 if blurry else 1.15)
            rgb = ImageEnhance.Sharpness(rgb).enhance(2.0 if blurry else 1.4)
            gray_pil = ImageOps.grayscale(rgb).filter(ImageFilter.SHARPEN)
            arr = np.array(gray_pil)
        _add(cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR))
    except Exception:
        logger.debug("paddle_ocr.pil_enhance_failed path=%s", image_path, exc_info=True)

    if blurry:
        logger.info(
            "paddle_ocr.blur_detected path=%s laplacian=%.1f variants=%d",
            image_path,
            _laplacian_variance(gray),
            len(variants),
        )

    return variants


def iter_ocr_text_passes(image_path: str):
    """Yield (text, confidence) per preprocessing pass — supports early exit upstream."""
    variants = _preprocess_variants(image_path)
    if not variants:
        return

    engine = _get_engine()
    seen_text: set[str] = set()

    for image in variants:
        try:
            ocr_result = engine.ocr(image, cls=True)
        except Exception:
            logger.warning("paddle_ocr.ocr_failed path=%s", image_path, exc_info=True)
            continue
        text, conf = _result_to_text(ocr_result)
        normalized = text.strip()
        if not normalized or normalized in seen_text:
            continue
        seen_text.add(normalized)
        yield text, conf


def extract_text_variants_from_image(image_path: str) -> List[Tuple[str, float]]:
    """Run PaddleOCR on each preprocessing variant; returns all non-empty texts."""
    results: List[Tuple[str, float]] = list(iter_ocr_text_passes(image_path))
    if not results:
        return []

    seen_text = {t.strip() for t, _ in results}
    merged = merge_variant_texts([t for t, _ in results])
    if merged and merged.strip() not in seen_text:
        avg_conf = sum(c for _, c in results) / len(results)
        results.append((merged, min(0.99, avg_conf + 0.05)))

    return results


def extract_text_from_image(image_path: str) -> Tuple[str, float]:
    """
    Run PaddleOCR on an image path with preprocessing variants.
    Returns (combined_best_text, engine_confidence).
    """
    results = extract_text_variants_from_image(image_path)
    if not results:
        return "", 0.0

    merged_candidates = [r for r in results if r[0].count("\n") >= 3]
    if merged_candidates:
        merged_candidates.sort(key=lambda r: (len(r[0]), r[1]))
        return merged_candidates[-1]

    best_text, best_conf = results[0]
    for text, conf in results[1:]:
        if conf > best_conf or (conf == best_conf and len(text) > len(best_text)):
            best_text = text
            best_conf = conf
    return best_text, best_conf
