import hashlib
import mimetypes
from io import BytesIO
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException, UploadFile
from PIL import Image
import logging

logger = logging.getLogger(__name__)


class MultiFileUploadHandler:
    """Handle multiple file uploads (images, PDFs, mixed types)."""

    ALLOWED_EXTENSIONS = [
        "jpg", "jpeg", "png", "pdf", "webp", "avif",
        "heic", "heif", "bmp", "tiff", "gif",
    ]
    MAX_TOTAL_SIZE = 50 * 1024 * 1024
    MAX_FILE_SIZE = 10 * 1024 * 1024

    @staticmethod
    async def process_multiple_files(files: List[UploadFile]) -> List[Dict]:
        if not files:
            return []

        total_size = 0
        for file in files:
            content = await file.read()
            total_size += len(content)
            await file.seek(0)

        if total_size > MultiFileUploadHandler.MAX_TOTAL_SIZE:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Total file size exceeds "
                    f"{MultiFileUploadHandler.MAX_TOTAL_SIZE // 1024 // 1024}MB limit"
                ),
            )

        processed_files = []
        for idx, file in enumerate(files):
            processed = await MultiFileUploadHandler.process_single_file(
                file, is_primary=(idx == 0)
            )
            processed_files.append(processed)
        return processed_files

    @staticmethod
    async def process_single_file(file: UploadFile, is_primary: bool = False) -> Dict:
        await MultiFileUploadHandler.validate_file(file)
        content = await file.read()

        if len(content) > MultiFileUploadHandler.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"File {file.filename} exceeds "
                    f"{MultiFileUploadHandler.MAX_FILE_SIZE // 1024 // 1024}MB limit"
                ),
            )

        file_extension = file.filename.split(".")[-1].lower()
        file_hash = hashlib.sha256(content).hexdigest()
        mime_type = mimetypes.guess_type(file.filename)[0]
        if not mime_type:
            mime_type = MultiFileUploadHandler.get_mime_type_from_extension(file_extension)

        thumbnail_data = None
        if mime_type.startswith("image/"):
            thumbnail_data = await MultiFileUploadHandler.create_thumbnail(content)

        return {
            "file_data": content,
            "file_name": file.filename,
            "file_size": len(content),
            "mime_type": mime_type,
            "file_hash": file_hash,
            "thumbnail_data": thumbnail_data,
            "is_primary": is_primary,
            "file_extension": file_extension,
        }

    @staticmethod
    async def validate_file(file: UploadFile) -> None:
        if not file.filename:
            raise HTTPException(status_code=400, detail="No filename provided")
        file_extension = file.filename.split(".")[-1].lower()
        if file_extension not in MultiFileUploadHandler.ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"File type '.{file_extension}' not allowed. "
                    f"Allowed: {', '.join(MultiFileUploadHandler.ALLOWED_EXTENSIONS)}"
                ),
            )

    @staticmethod
    def get_mime_type_from_extension(extension: str) -> str:
        mime_types = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
            "avif": "image/avif",
            "heic": "image/heic",
            "heif": "image/heif",
            "bmp": "image/bmp",
            "tiff": "image/tiff",
            "gif": "image/gif",
            "pdf": "application/pdf",
        }
        return mime_types.get(extension, "application/octet-stream")

    @staticmethod
    async def create_thumbnail(
        image_data: bytes, size: Tuple[int, int] = (200, 200)
    ) -> Optional[bytes]:
        try:
            image = Image.open(BytesIO(image_data))
            if image.mode in ("RGBA", "LA", "P"):
                background = Image.new("RGB", image.size, (255, 255, 255))
                if image.mode == "P":
                    image = image.convert("RGBA")
                if image.mode == "RGBA":
                    background.paste(image, mask=image.split()[-1])
                else:
                    background.paste(image)
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")
            image.thumbnail(size, Image.Resampling.LANCZOS)
            thumbnail_buffer = BytesIO()
            image.save(thumbnail_buffer, format="JPEG", quality=85, optimize=True)
            return thumbnail_buffer.getvalue()
        except Exception as e:
            logger.warning(f"Thumbnail creation failed: {e}")
            return None


# Backward-compatible aliases
DatabaseFileHandler = MultiFileUploadHandler


async def process_multiple_files(files: List[UploadFile]) -> List[Dict]:
    return await MultiFileUploadHandler.process_multiple_files(files)


async def process_single_file(file: UploadFile, is_primary: bool = False) -> Dict:
    return await MultiFileUploadHandler.process_single_file(file, is_primary)


async def process_uploaded_file(file: UploadFile) -> Dict:
    return await MultiFileUploadHandler.process_single_file(file, is_primary=True)
