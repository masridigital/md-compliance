"""
Cross-framework control mapping utility.

Populates the ``Control.mapping`` JSON field with cross-references
between frameworks.  Uses NIST 800-53 Rev 5 as the hub — each NIST
control has known equivalents in SOC 2, ISO 27001, PCI DSS v4.0,
HIPAA, CMMC, and NIST CSF.

Usage:
    from app.masri.control_mappings import populate_mappings
    populate_mappings(tenant_id)   # backfill all controls for a tenant
"""

import json
import logging
import os

from flask import current_app

logger = logging.getLogger(__name__)

# Framework identifier → JSON filename (without .json)
_FRAMEWORK_FILE_KEYS = {
    "nist_800_53_v5": "nist_800_53_v5",
    "soc2": "soc2",
    "iso_27001_2022": "iso_27001_2022",
    "pci_dss_v4.0": "pci_dss_v4.0",
    "hipaa_v2": "hipaa_v2",
    "cmmc_v2": "cmmc_v2",
    "nist_csf_v2.0": "nist_csf_v2.0",
}

_mappings_cache = None


def _load_mappings():
    """Load the cross-framework mapping data (cached)."""
    global _mappings_cache
    if _mappings_cache is not None:
        return _mappings_cache

    mapping_file = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "files",
        "cross_framework_mappings.json",
    )
    try:
        with open(mapping_file) as f:
            data = json.load(f)
        _mappings_cache = data.get("mappings", {})
    except Exception:
        logger.exception("Failed to load cross-framework mappings")
        _mappings_cache = {}
    return _mappings_cache


def _build_reverse_index(mappings):
    """
    Build a reverse index: for every non-NIST framework, map its ref_codes
    back to NIST 800-53 controls and to all other frameworks that share
    the same NIST parent.

    Returns: {framework_key: {ref_code_lower: {other_fw: [codes]}}}
    """
    reverse = {}
    for nist_code, fw_map in mappings.items():
        for fw_key, codes in fw_map.items():
            for code in codes:
                code_lower = code.lower()
                reverse.setdefault(fw_key, {}).setdefault(code_lower, {})
                # Add NIST back-reference
                reverse[fw_key][code_lower].setdefault("nist_800_53_v5", [])
                if nist_code not in reverse[fw_key][code_lower]["nist_800_53_v5"]:
                    reverse[fw_key][code_lower]["nist_800_53_v5"].append(nist_code)
                # Add cross-references to other frameworks
                for other_fw, other_codes in fw_map.items():
                    if other_fw != fw_key and other_codes:
                        reverse[fw_key][code_lower].setdefault(other_fw, [])
                        for oc in other_codes:
                            if oc not in reverse[fw_key][code_lower][other_fw]:
                                reverse[fw_key][code_lower][other_fw].append(oc)
    return reverse


def get_mapping_for_control(framework_name, ref_code):
    """
    Get cross-framework mappings for a single control.

    Args:
        framework_name: Framework file key (e.g., "nist_800_53_v5", "soc2")
        ref_code: The control's ref_code (e.g., "AC-2", "cc6.1")

    Returns:
        dict: {framework_key: [ref_codes]} or empty dict
    """
    mappings = _load_mappings()
    framework_name = framework_name.lower()
    ref_upper = ref_code.upper() if ref_code else ""
    ref_lower = ref_code.lower() if ref_code else ""

    # Direct lookup for NIST 800-53 controls
    if framework_name == "nist_800_53_v5" and ref_upper in mappings:
        return mappings[ref_upper]

    # Reverse lookup for other frameworks
    reverse = _build_reverse_index(mappings)
    fw_key = framework_name
    if fw_key in reverse and ref_lower in reverse[fw_key]:
        return reverse[fw_key][ref_lower]

    return {}


def populate_mappings(tenant_id):
    """
    Backfill ``Control.mapping`` for all controls belonging to a tenant.

    Only updates controls that have empty or null mappings.  Safe to run
    multiple times.

    Returns:
        int: Number of controls updated
    """
    from app import db
    from app.models import Control, Framework

    mappings = _load_mappings()
    if not mappings:
        logger.warning("No cross-framework mapping data available")
        return 0

    reverse = _build_reverse_index(mappings)

    # Get all frameworks for this tenant
    frameworks = db.session.execute(
        db.select(Framework).filter_by(tenant_id=tenant_id)
    ).scalars().all()

    fw_name_map = {}
    for fw in frameworks:
        fw_name_map[fw.id] = fw.name.lower()

    updated = 0
    controls = db.session.execute(
        db.select(Control).filter_by(tenant_id=tenant_id)
    ).scalars().all()

    for control in controls:
        if not control.ref_code:
            continue

        # Determine framework name from the control's abs_ref_code
        fw_name = None
        if control.abs_ref_code and "__" in control.abs_ref_code:
            fw_name = control.abs_ref_code.split("__")[0]
        if not fw_name:
            # Fallback: look up from framework_id
            for fid, fname in fw_name_map.items():
                # Controls link to frameworks via their tenant + ref pattern
                if control.abs_ref_code and control.abs_ref_code.startswith(fname):
                    fw_name = fname
                    break

        if not fw_name:
            continue

        ref_upper = control.ref_code.upper()
        ref_lower = control.ref_code.lower()

        # Build mapping for this control
        new_mapping = {}

        if fw_name == "nist_800_53_v5" and ref_upper in mappings:
            new_mapping = dict(mappings[ref_upper])
        elif fw_name in reverse and ref_lower in reverse[fw_name]:
            new_mapping = dict(reverse[fw_name][ref_lower])

        if new_mapping:
            # Merge with existing mapping if any
            existing = control.mapping or {}
            merged = dict(existing)
            for k, v in new_mapping.items():
                if k not in merged:
                    merged[k] = v
                else:
                    # Deduplicate
                    existing_set = set(merged[k]) if isinstance(merged[k], list) else set()
                    new_set = set(v) if isinstance(v, list) else set()
                    merged[k] = list(existing_set | new_set)

            if merged != existing:
                control.mapping = merged
                updated += 1

    if updated:
        db.session.commit()
        logger.info(
            "Populated cross-framework mappings for %d controls (tenant %s)",
            updated, tenant_id,
        )

    return updated
