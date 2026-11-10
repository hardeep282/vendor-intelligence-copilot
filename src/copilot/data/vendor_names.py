"""One name per vendor: the merges the analytics project's Gold views already apply.

Purpose : the source workbook's vendor views come from `dbo.vw_VendorSalesBase`, which gives each
          vendor number one canonical name (the name with the most SKU rows). The raw
          `output_monthly_demand` sheet has vendor names but no vendor numbers, so its two extra
          spellings are mapped here by name, to exactly the same canonical names.
Inputs  : none (a constant, copied from `SQL Analysis/Vendor_analysis.sql` in the analytics
          project, where the view is defined).
Outputs : `VENDOR_NAME_ALIASES`, used by `scripts/build_snapshot.py` when it aggregates the monthly
          sheet, and checked by `tests/test_snapshot_reconciliation.py`.

Added 10 Nov 2026 (RAID R14). Before this, the monthly table listed SOUTHERN GLAZERS W&S OF NE and
VINEYARD BRANDS LLC as separate vendors, so a join to the vendor tables silently dropped them.
If the view's merges ever change, change this mapping with them.
"""

from __future__ import annotations

VENDOR_NAME_ALIASES: dict[str, str] = {
    "SOUTHERN GLAZERS W&S OF NE": "SOUTHERN WINE & SPIRITS NE",  # VendorNumber 2000
    "VINEYARD BRANDS LLC": "VINEYARD BRANDS INC",  # VendorNumber 1587
}

__all__ = ["VENDOR_NAME_ALIASES"]
