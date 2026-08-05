from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any


_APP = None


def _app_root() -> Path:
    configured = os.getenv(
        "KUSHWELL_APP_ROOT",
        r"C:\Users\Kushwell",
    )
    return Path(configured).expanduser().resolve()


def _load_app():
    global _APP

    if _APP is not None:
        return _APP

    root = _app_root()

    if not root.exists():
        raise RuntimeError(
            f"Kushwell application root does not exist: {root}"
        )

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    # Prevent the Flask app from starting another Brain process while
    # Atlas enters the application to use KAP.
    os.environ["KUSHWELL_SKIP_BRAIN_AUTOSTART"] = "1"

    from app import create_app

    _APP = create_app()
    return _APP


@contextmanager
def kushwell_app_context():
    app = _load_app()

    with app.app_context():
        yield app


def acquisition_status(args: dict[str, Any] | None = None) -> dict:
    args = args or {}

    with kushwell_app_context():
        from app.services.acquisition import (
            AcquisitionRunLedger,
            RegionalAcquisitionRegistry,
        )

        registry = RegionalAcquisitionRegistry()
        ledger = AcquisitionRunLedger()

        return {
            "status": "ok",
            "registry": registry.summary(),
            "ledger": ledger.summary(),
            "requested_by": args.get("requested_by"),
        }


def acquisition_runs(args: dict[str, Any] | None = None) -> dict:
    args = args or {}
    limit = max(1, min(int(args.get("limit") or 25), 200))

    with kushwell_app_context():
        from app.services.acquisition import AcquisitionRunLedger

        ledger = AcquisitionRunLedger()

        return {
            "status": "ok",
            "ledger_available": ledger.is_available(),
            "summary": ledger.summary(),
            "runs": [
                row.to_dict()
                for row in ledger.recent(limit=limit)
            ],
        }


def plan_product_acquisition(args: dict[str, Any]) -> dict:
    with kushwell_app_context():
        from app.services.acquisition import (
            ProductAcquisitionRequest,
            ProductAcquisitionService,
        )

        request = ProductAcquisitionRequest(
            jurisdiction_code=str(
                args.get("jurisdiction_code") or "CA"
            ),
            provider_key=str(
                args.get("provider_key") or "weedmaps"
            ),
            start_id=int(args.get("start_id") or 1),
            batch_size=int(args.get("batch_size") or 25),
            max_batches=int(args.get("max_batches") or 1),
            dry_run=True,
            triggered_by=str(
                args.get("triggered_by") or "atlas"
            ),
            trigger_type="atlas",
        )

        return ProductAcquisitionService().run(request)


def run_product_acquisition(args: dict[str, Any]) -> dict:
    """
    Execute one governed acquisition run.

    Live execution is intentionally impossible unless the planner sends
    both dry_run=False and confirm_live=True.
    """
    dry_run = bool(args.get("dry_run", True))
    confirm_live = bool(args.get("confirm_live", False))

    if not dry_run and not confirm_live:
        raise PermissionError(
            "Atlas refused live acquisition because explicit "
            "confirmation was not supplied."
        )

    with kushwell_app_context():
        from app.services.acquisition import (
            ProductAcquisitionRequest,
            ProductAcquisitionService,
        )

        request = ProductAcquisitionRequest(
            jurisdiction_code=str(
                args.get("jurisdiction_code") or "CA"
            ),
            provider_key=str(
                args.get("provider_key") or "weedmaps"
            ),
            start_id=int(args.get("start_id") or 1),
            batch_size=int(args.get("batch_size") or 25),
            max_batches=int(args.get("max_batches") or 1),
            dry_run=dry_run,
            triggered_by=str(
                args.get("triggered_by") or "atlas"
            ),
            trigger_type="atlas",
        )

        return ProductAcquisitionService().run(request)
