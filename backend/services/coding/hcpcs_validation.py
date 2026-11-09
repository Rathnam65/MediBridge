"""Conservative HCPCS checks; catalog presence is not coverage approval."""
import re


def validate_hcpcs_recommendation(code, documented_text, records, effective_date=None, modifiers=None):
    match = next(
        (item for item in records if item.get("code", "").upper() == code.upper()),
        None,
    )
    if match is None:
        return {
            "status": "unsupported",
            "supported": False,
            "review_required": True,
            "evidence": [],
            "flags": ["Code is not present in the supplied HCPCS catalog."],
        }

    flags = []
    if effective_date is None:
        flags.append("Catalog effective dates are not available for this code.")
    if modifiers:
        flags.append("Modifier applicability is not available in the supplied source.")
    if not re.search(r"[A-Za-z]", documented_text):
        flags.append("Documentation does not contain a service description to compare.")
    flags.append(
        "Catalog matching does not establish payer coverage or medical necessity."
    )
    return {
        "status": "catalog_match_needs_review",
        "supported": True,
        "review_required": True,
        "evidence": [{
            "source": match.get("source_file", "HCPCS catalog"),
            "catalog_version": match.get("catalog_version", "2026_Q4"),
            "code": match["code"],
            "description": match.get("description", ""),
        }],
        "flags": flags,
    }
