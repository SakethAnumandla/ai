"""Tamper-evident export metadata for compliance and audit integrity."""
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config import settings


class ExportSignatureService:
    """
    Attach HMAC signature to export manifests.

    Future: asymmetric keys, external verification API, WORM storage.
    """

    def __init__(self, signing_secret: Optional[str] = None):
        self._secret = signing_secret or getattr(
            settings, "export_signing_secret", ""
        ) or "dev-export-signing-not-for-production"

    def sign_manifest(
        self,
        manifest: Dict[str, Any],
        *,
        content_bytes: Optional[bytes] = None,
        exported_by: Optional[int] = None,
        tenant_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not getattr(settings, "export_signatures_enabled", False):
            return {
                "signing_enabled": False,
                "note": "Set EXPORT_SIGNATURES_ENABLED=true for tamper-evident exports.",
            }

        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
        content_hash = None
        if content_bytes is not None:
            content_hash = hashlib.sha256(content_bytes).hexdigest()

        payload = canonical
        if content_hash:
            payload = f"{content_hash}:{canonical}"

        signature = hmac.new(
            self._secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return {
            "signing_enabled": True,
            "algorithm": "HMAC-SHA256",
            "content_sha256": content_hash,
            "signature": signature,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "exported_by": exported_by,
            "tenant_id": tenant_id,
            "manifest_version": "1",
        }

    def verify_manifest(
        self,
        manifest: Dict[str, Any],
        signature_block: Dict[str, Any],
        *,
        content_bytes: Optional[bytes] = None,
    ) -> bool:
        if not signature_block.get("signing_enabled"):
            return False
        expected = self.sign_manifest(
            manifest,
            content_bytes=content_bytes,
            exported_by=signature_block.get("exported_by"),
            tenant_id=signature_block.get("tenant_id"),
        )
        return hmac.compare_digest(
            expected.get("signature", ""),
            signature_block.get("signature", ""),
        )
