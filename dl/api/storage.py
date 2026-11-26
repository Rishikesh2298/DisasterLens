"""
Secure image storage service and validation for DisasterLens.

Handles file validation, content inspection, size limits, path traversal prevention,
server-controlled unique naming, and storage abstractions.
"""

from __future__ import annotations

import io
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from PIL import Image

# Supported formats and signatures
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}
ALLOWED_MIME_TYPES = {"image/png", "image/jpeg"}

# Magic number signatures
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"


class ImageStorageService:
    """
    Manages local image upload lifecycle, validation, storage, and cleanup.
    """

    def __init__(
        self,
        upload_dir: str = "uploads",
        max_size_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        self.upload_dir = Path(upload_dir)
        self.max_size_bytes = max_size_bytes

    def _ensure_upload_dir(self) -> Path:
        """Ensures the upload directory exists and returns its resolved Path."""
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        return self.upload_dir

    def sanitize_filename(self, filename: str | None) -> str:
        """
        Sanitizes client-provided filename to prevent path traversal or unsafe characters.
        Extracts only the basename and replaces risky characters.
        """
        if not filename:
            return "unnamed_upload.png"

        # Prevent directory traversal attacks
        base = Path(filename).name

        # Strip null bytes and control chars
        sanitized = re.sub(r"[^\w\.\-_]", "_", base)
        return sanitized or "unnamed_upload.png"

    async def validate_and_save(
        self,
        file: UploadFile,
    ) -> tuple[str, str, int]:
        """
        Validates uploaded file content, size, and format, then persists to storage.

        Returns:
            Tuple of (storage_reference, sanitized_original_filename, byte_size)
            Note: storage_reference is a server-controlled relative key (e.g. 'uploads/uuid_ts.png').
                  Never exposes absolute local filesystem paths in public responses.

        Raises:
            HTTPException with 400 on empty, corrupt, unsupported, or oversized uploads.
        """
        original_name = self.sanitize_filename(file.filename)
        ext = Path(original_name).suffix.lower()

        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported image extension '{ext}'. Supported formats: PNG, JPEG.",
            )

        # Read contents with size guard
        try:
            content = await file.read()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {e!s}")

        byte_size = len(content)

        if byte_size == 0:
            raise HTTPException(status_code=400, detail="Uploaded image file is empty (0 bytes).")

        if byte_size > self.max_size_bytes:
            max_mb = self.max_size_bytes // (1024 * 1024)
            raise HTTPException(
                status_code=400,
                detail=f"Uploaded image exceeds maximum size limit of {max_mb} MB ({byte_size} bytes).",
            )

        # Validate magic numbers
        is_png = content.startswith(PNG_MAGIC)
        is_jpeg = content.startswith(JPEG_MAGIC)

        if not (is_png or is_jpeg):
            raise HTTPException(
                status_code=400,
                detail="Invalid image format: File header does not match PNG or JPEG magic bytes.",
            )

        # Verify image content integrity via Pillow
        try:
            with Image.open(io.BytesIO(content)) as img:
                img.verify()
                img_format = (img.format or "").upper()
                if img_format not in {"PNG", "JPEG"}:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Unsupported image format '{img_format}'. Supported formats: PNG, JPEG.",
                    )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Corrupt or invalid image content: {e!s}",
            )

        # Generate unique server-controlled storage filename
        timestamp = int(datetime.now(UTC).timestamp())
        unique_name = f"{uuid4().hex}_{timestamp}{ext}"

        # Persist to disk
        target_dir = self._ensure_upload_dir()
        target_file = target_dir / unique_name

        try:
            with open(target_file, "wb") as f:  # noqa: ASYNC230
                f.write(content)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to persist image to disk: {e!s}",
            )

        # Relative storage key, never absolute filesystem path
        storage_ref = f"{self.upload_dir.name}/{unique_name}"
        return storage_ref, original_name, byte_size

    def delete_file(self, storage_ref: str | None) -> bool:
        """
        Safely cleans up an orphaned image file on transaction failure.
        """
        if not storage_ref:
            return False
        try:
            filename = Path(storage_ref).name
            target = self.upload_dir / filename
            if target.exists() and target.is_file():
                os.remove(target)
                return True
        except Exception:
            pass
        return False
