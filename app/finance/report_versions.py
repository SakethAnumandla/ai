"""Report versioning — reproducible executive pack definitions."""
from typing import Any, Dict, Optional


REPORT_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "executive_pack_v1": {
        "report_type": "executive_pack",
        "schema_version": 1,
        "sections": [
            "spend_trends",
            "vendors",
            "departments",
            "policy",
            "approval_health",
        ],
        "description": "Month-end executive bundle (Phase 6/7 baseline).",
    },
    "spend_trends_v1": {
        "report_type": "spend_trends",
        "schema_version": 1,
        "sections": ["mom_changes", "by_month", "narrative"],
    },
    "vendor_breakdown_v1": {
        "report_type": "vendor_breakdown",
        "schema_version": 1,
        "sections": ["vendors", "total_spend", "narrative"],
    },
    "department_analysis_v1": {
        "report_type": "department_analysis",
        "schema_version": 1,
        "sections": ["departments", "total_spend"],
    },
}

DEFAULT_REPORT_VERSION = "executive_pack_v1"


def resolve_report_spec(
    report_type: Optional[str] = None,
    report_version: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolve report_type + version for manifest reproducibility.
    If report_version is set, it wins; otherwise infer from report_type or default.
    """
    if report_version:
        spec = REPORT_DEFINITIONS.get(report_version)
        if not spec:
            raise ValueError(f"Unknown report version: {report_version}")
        return {
            "report_version": report_version,
            "report_type": spec["report_type"],
            "schema_version": spec.get("schema_version", 1),
            "sections": spec.get("sections", []),
        }

    if report_type:
        for version, spec in REPORT_DEFINITIONS.items():
            if spec["report_type"] == report_type:
                return {
                    "report_version": version,
                    "report_type": report_type,
                    "schema_version": spec.get("schema_version", 1),
                    "sections": spec.get("sections", []),
                }
        return {
            "report_version": f"{report_type}_v0",
            "report_type": report_type,
            "schema_version": 0,
            "sections": [],
        }

    spec = REPORT_DEFINITIONS[DEFAULT_REPORT_VERSION]
    return {
        "report_version": DEFAULT_REPORT_VERSION,
        "report_type": spec["report_type"],
        "schema_version": spec["schema_version"],
        "sections": spec["sections"],
    }


def list_report_versions() -> Dict[str, Any]:
    return {
        "default": DEFAULT_REPORT_VERSION,
        "versions": {
            k: {
                "report_type": v["report_type"],
                "schema_version": v.get("schema_version"),
                "description": v.get("description"),
            }
            for k, v in REPORT_DEFINITIONS.items()
        },
    }
