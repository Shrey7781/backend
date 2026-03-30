from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.pack_test import PackTest
from app.models.battery_pack import Battery, BatteryCellMapping
from app.models.battery import BatteryModel
from app.models.cell import Cell
from pydantic import BaseModel
from typing import List, Optional
import io
import pandas as pd
from app.core.signals import trigger_dashboard_update

router = APIRouter(prefix="/batteries", tags=["Battery Production"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class AssignCellsRequest(BaseModel):
    battery_id: str
    cell_ids:   List[str]

    # All ranges optional — only checked when BOTH bounds are provided
    cell_ir_lower:       Optional[float] = None
    cell_ir_upper:       Optional[float] = None
    cell_voltage_lower:  Optional[float] = None
    cell_voltage_upper:  Optional[float] = None
    cell_capacity_lower: Optional[float] = None
    cell_capacity_upper: Optional[float] = None


class ReplaceCellRequest(BaseModel):
    battery_id:  str
    old_cell_id: str
    new_cell_id: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _validate_cell_ranges(cell: Cell, battery: Battery) -> Optional[dict]:
    """
    Check cell parameters against ranges stored on the Battery record.
    A parameter is only checked when BOTH its lower and upper bounds are not None.
    Returns None if the cell passes all checks, or a dict describing failures.
    """
    failures = {}

    if battery.cell_ir_lower is not None and battery.cell_ir_upper is not None:
        if cell.ir_value_m_ohm is None or not (
            battery.cell_ir_lower <= cell.ir_value_m_ohm <= battery.cell_ir_upper
        ):
            failures["ir"] = {
                "actual":   cell.ir_value_m_ohm,
                "expected": f"{battery.cell_ir_lower}–{battery.cell_ir_upper} mΩ"
            }

    if battery.cell_voltage_lower is not None and battery.cell_voltage_upper is not None:
        if cell.sorting_voltage is None or not (
            battery.cell_voltage_lower <= cell.sorting_voltage <= battery.cell_voltage_upper
        ):
            failures["voltage"] = {
                "actual":   cell.sorting_voltage,
                "expected": f"{battery.cell_voltage_lower}–{battery.cell_voltage_upper} V"
            }

    if battery.cell_capacity_lower is not None and battery.cell_capacity_upper is not None:
        if cell.discharging_capacity_mah is None or not (
            battery.cell_capacity_lower <= cell.discharging_capacity_mah <= battery.cell_capacity_upper
        ):
            failures["capacity"] = {
                "actual":   cell.discharging_capacity_mah,
                "expected": f"{battery.cell_capacity_lower}–{battery.cell_capacity_upper} mAh"
            }

    return failures if failures else None


# ── Range-window chemistry rules ──────────────────────────────────────────────

_RANGE_RULES = {
    "NMC": {"ir_max_window": 0.20, "voltage_max_window": 0.005, "capacity_max_window": 5.0},
    "LFP": {"ir_max_window": 0.04, "voltage_max_window": 0.004, "capacity_max_window": 0.5},
}

def _validate_range_windows(data: AssignCellsRequest, cell_type: str) -> list:
    """
    Validate that operator-supplied ranges are within allowed tolerances
    for the given cell chemistry. Returns list of error strings (empty = OK).
    """
    errors = []
    rules  = _RANGE_RULES.get(cell_type.upper())
    if not rules:
        return errors

    if data.cell_ir_lower is not None and data.cell_ir_upper is not None:
        if data.cell_ir_upper < data.cell_ir_lower:
            errors.append("IR: upper bound must be ≥ lower bound")
        else:
            window = round(data.cell_ir_upper - data.cell_ir_lower, 6)
            if window > rules["ir_max_window"]:
                errors.append(
                    f"IR range window is {window} mΩ — "
                    f"maximum allowed for {cell_type} is {rules['ir_max_window']} mΩ"
                )

    if data.cell_voltage_lower is not None and data.cell_voltage_upper is not None:
        if data.cell_voltage_upper < data.cell_voltage_lower:
            errors.append("Voltage: upper bound must be ≥ lower bound")
        else:
            window = round(data.cell_voltage_upper - data.cell_voltage_lower, 6)
            if window > rules["voltage_max_window"]:
                errors.append(
                    f"Voltage range window is {window} V — "
                    f"maximum allowed for {cell_type} is {rules['voltage_max_window']} V"
                )

    if data.cell_capacity_lower is not None and data.cell_capacity_upper is not None:
        if data.cell_capacity_upper < data.cell_capacity_lower:
            errors.append("Capacity: upper bound must be ≥ lower bound")
        else:
            window = round(data.cell_capacity_upper - data.cell_capacity_lower, 6)
            if window > rules["capacity_max_window"]:
                errors.append(
                    f"Capacity range window is {window} mAh — "
                    f"maximum allowed for {cell_type} is {rules['capacity_max_window']} mAh"
                )

    return errors


# ── Assign Cells ──────────────────────────────────────────────────────────────

@router.post("/assign-cells")
async def assign_cells_to_battery(
    data: AssignCellsRequest,
    db:   Session = Depends(get_db)
):
    """
    Validate and assign a list of cells to a battery pack.

    Performance — all DB work done BEFORE the validation loop:
      1 query  → Battery record
      1 query  → BatteryModel record
      1 query  → ALL Cell records in one IN() lookup   (was 1 per cell)
      1 query  → existing mappings for this battery    (duplicate scan check)
      1 commit → mappings insert + cell.is_used update

    Total: 4–5 round-trips regardless of how many cells are in the pack.
    Previously: 2 + N queries where N = number of cells (e.g. 130 for a 13S10P pack).
    """

    # ── 1. Fetch battery ──────────────────────────────────────────────────────
    battery = db.query(Battery).filter(Battery.battery_id == data.battery_id).first()
    if not battery:
        raise HTTPException(
            status_code=404,
            detail="Battery ID not found. Register it via bulk-link first."
        )

    # ── 2. Fetch model + validate range windows ───────────────────────────────
    model = db.query(BatteryModel).filter(BatteryModel.model_id == battery.model_id).first()
    if model:
        range_errors = _validate_range_windows(data, model.cell_type.value)
        if range_errors:
            raise HTTPException(status_code=422, detail={
                "error":      "Supplied ranges violate cell chemistry tolerances",
                "cell_type":  model.cell_type.value,
                "violations": range_errors
            })

    # ── 3. Persist session ranges onto Battery (audit trail) ──────────────────
    battery.cell_ir_lower       = data.cell_ir_lower
    battery.cell_ir_upper       = data.cell_ir_upper
    battery.cell_voltage_lower  = data.cell_voltage_lower
    battery.cell_voltage_upper  = data.cell_voltage_upper
    battery.cell_capacity_lower = data.cell_capacity_lower
    battery.cell_capacity_upper = data.cell_capacity_upper

    # ── 4. Catch duplicate cell IDs in the submitted list ─────────────────────
    if len(data.cell_ids) != len(set(data.cell_ids)):
        seen, dupes = set(), []
        for cid in data.cell_ids:
            if cid in seen:
                dupes.append(cid)
            seen.add(cid)
        return {
            "status":        "Error",
            "message":       "Duplicate cell IDs in submitted list",
            "invalid_cells": [{"cell_id": d, "reason": "Scanned twice in this session"} for d in dupes]
        }

    # ── 5. BULK FETCH all cells in one query ──────────────────────────────────
    #    Previously: db.query(Cell).filter(Cell.cell_id == cid).first() inside loop
    #    Now: single WHERE cell_id IN (...) — zero DB queries inside the loop
    cells_in_db = db.query(Cell).filter(Cell.cell_id.in_(data.cell_ids)).all()
    cell_map    = {c.cell_id: c for c in cells_in_db}

    # ── 6. BULK FETCH existing mappings for this battery ─────────────────────
    #    Prevents re-assigning a cell that was already mapped in a previous session
    existing_mappings  = db.query(BatteryCellMapping).filter(
        BatteryCellMapping.battery_id == data.battery_id
    ).all()
    already_in_battery = {m.cell_id for m in existing_mappings}

    # ── 7. Determine cell_type once (used in sorting check) ──────────────────
    cell_type = ""
    if model:
        cell_type = (
            model.cell_type.value if hasattr(model.cell_type, "value")
            else str(model.cell_type)
        ).upper()
    is_nmc = (cell_type == "NMC")

    # ── 8. Validate each cell IN MEMORY — zero DB queries inside this loop ────
    invalid_cells  = []
    valid_mappings = []
    cells_to_mark  = []

    for cid in data.cell_ids:

        cell = cell_map.get(cid)

        # 8a. Cell must exist in inventory
        if not cell:
            invalid_cells.append({
                "cell_id": cid,
                "reason":  "Cell ID not registered in inventory"
            })
            continue

        # 8b. Must not be used by another battery
        if cell.is_used:
            invalid_cells.append({
                "cell_id": cid,
                "reason":  "Cell already assigned to another battery pack"
            })
            continue

        # 8c. Must not already be mapped to THIS battery
        if cid in already_in_battery:
            invalid_cells.append({
                "cell_id": cid,
                "reason":  "Cell is already mapped to this battery"
            })
            continue

        # 8d. Must have passed grading
        if cell.status != "pass":
            invalid_cells.append({
                "cell_id": cid,
                "reason":  (
                    f"Cell has not passed grading "
                    f"(status: {cell.status.upper() if cell.status else 'NOT GRADED'})"
                )
            })
            continue

        # 8e. NMC requires sorting data; LFP does not
        if is_nmc and cell.sorting_date is None:
            invalid_cells.append({
                "cell_id": cid,
                "reason":  (
                    "Sorting data not found. NMC batteries require a sorting "
                    "report before assembly. Please upload the sorting file for this cell."
                )
            })
            continue

        # 8f. Parameter range checks (uses ranges saved on battery in step 3)
        failures = _validate_cell_ranges(cell, battery)
        if failures:
            invalid_cells.append({
                "cell_id": cid,
                "reason":  "Parameter out of range",
                "details": failures
            })
            continue

        # ── All checks passed ─────────────────────────────────────────────────
        valid_mappings.append(BatteryCellMapping(battery_id=data.battery_id, cell_id=cid))
        cells_to_mark.append(cell)

    # ── 9. Atomic — reject everything if any cell fails ───────────────────────
    if invalid_cells:
        db.rollback()  # discard the range save from step 3
        return {
            "status":        "Error",
            "message":       "Validation failed — no cells were assigned",
            "invalid_cells": invalid_cells
        }

    # ── 10. Commit — bulk insert mappings + mark cells used ───────────────────
    try:
        db.add_all(valid_mappings)
        for cell in cells_to_mark:
            cell.is_used = True
        db.commit()
        await trigger_dashboard_update()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    ranges_applied = {
        k: v for k, v in {
            "ir":       f"{data.cell_ir_lower}–{data.cell_ir_upper} mΩ"
                        if data.cell_ir_lower is not None else None,
            "voltage":  f"{data.cell_voltage_lower}–{data.cell_voltage_upper} V"
                        if data.cell_voltage_lower is not None else None,
            "capacity": f"{data.cell_capacity_lower}–{data.cell_capacity_upper} mAh"
                        if data.cell_capacity_lower is not None else None,
        }.items() if v is not None
    }

    return {
        "status":         "Success",
        "message":        f"Assigned {len(valid_mappings)} cells to {data.battery_id}",
        "ranges_applied": ranges_applied or "None — all cells accepted without parameter checks"
    }


# ── Pack Test Upload ───────────────────────────────────────────────────────────

@router.post("/upload-report")
async def upload_pack_report_excel(
    file: UploadFile = File(...),
    db:   Session = Depends(get_db)
):
    """
    Upload pack test results (Excel).

    Performance:
      1 query → all Battery records in the file (bulk IN)
      1 query → all existing PackTest records   (bulk IN)
      All mutations in-memory
      1 bulk insert for new PackTest rows
      1 commit
    """
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Please upload an Excel file (.xlsx or .xls)")

    try:
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))
        df.columns = df.columns.str.strip()

        # Validate required columns
        required = ['Barcode', 'final Result', 'Date']
        missing  = [c for c in required if c not in df.columns]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required columns: {', '.join(missing)}"
            )

        df['Barcode'] = df['Barcode'].astype(str).str.strip()
        battery_ids  = df['Barcode'].tolist()

        # ── Bulk fetch batteries and existing pack tests ───────────────────────
        batteries     = db.query(Battery).filter(Battery.battery_id.in_(battery_ids)).all()
        battery_map   = {b.battery_id: b for b in batteries}

        pack_tests    = db.query(PackTest).filter(PackTest.battery_id.in_(battery_ids)).all()
        pack_test_map = {p.battery_id: p for p in pack_tests}

        skipped_batteries  = []
        ng_marked          = []
        passed_and_updated = []
        new_pack_tests     = []

        for _, row in df.iterrows():
            bid = str(row['Barcode']).strip()

            battery = battery_map.get(bid)
            if not battery:
                skipped_batteries.append(bid)
                continue

            current_status = str(row['final Result']).strip().upper()

            if current_status == "FAIL":
                battery.had_ng_status = True
                ng_marked.append(bid)
            elif current_status == "PASS":
                # Advance status to FG PENDING so battery appears in PDI queue
                battery.overall_status = "FG PENDING"
                passed_and_updated.append(bid)

            report_data = {
                "test_date":             row.get('Date'),
                "specification":         str(row.get('Specification', '')),
                "cell_type":             str(row.get('Cell type', '')),
                "actual_cap": float(row.get('Actual Capacity(Ah)',0)),
                "ocv_voltage":           float(row.get('OCV Voltage(V)', 0)),
                "upper_cutoff":          float(row.get('Upper cut off(V)', 0)),
                "lower_cutoff":          float(row.get('Lower cut off(V)', 0)),
                "discharging_capacity":  float(row.get('Discharging Capacity(Ah)', 0)),
                "capacity_result":       str(row.get('Result', '')),
                "idle_difference":       float(row.get('Final idle Different', 0)),
                "idle_diff_res":          str(row.get('idle diff. Result', '')),
                "final_voltage":         float(row.get('Final Voltage', 0)),
                "final_result":          current_status,
            }

            existing_report = pack_test_map.get(bid)
            if existing_report:
                for k, v in report_data.items():
                    setattr(existing_report, k, v)
            else:
                new_report = PackTest(battery_id=bid, **report_data)
                new_pack_tests.append(new_report)
                pack_test_map[bid] = new_report

        if new_pack_tests:
            db.bulk_save_objects(new_pack_tests)

        db.commit()
        await trigger_dashboard_update()

        return {
            "status": "Success",
            "summary": {
                "total_rows":           len(df),
                "processed":            len(ng_marked) + len(passed_and_updated),
                "marked_as_ng":         len(ng_marked),
                "passed_and_updated":   len(passed_and_updated),
                "skipped_unregistered": skipped_batteries
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error processing Excel: {str(e)}")


# ── Replace Cell ──────────────────────────────────────────────────────────────

@router.post("/replace-cell")
async def replace_leaked_cell(
    data: ReplaceCellRequest,
    db:   Session = Depends(get_db)
):
    """
    Atomically swap a faulty cell in an assembled battery pack.
    All fetches happen upfront; no DB queries inside conditional branches.
    """

    # Fetch everything needed in one go
    battery = db.query(Battery).filter(Battery.battery_id == data.battery_id).first()
    if not battery:
        raise HTTPException(status_code=404, detail="Battery Serial Number not found")

    old_mapping = db.query(BatteryCellMapping).filter(
        BatteryCellMapping.battery_id == data.battery_id,
        BatteryCellMapping.cell_id    == data.old_cell_id
    ).first()
    if not old_mapping:
        raise HTTPException(status_code=404, detail="Old cell is not linked to this battery")

    # Fetch both old and new cell in one query
    cells = db.query(Cell).filter(
        Cell.cell_id.in_([data.old_cell_id, data.new_cell_id])
    ).all()
    cell_map     = {c.cell_id: c for c in cells}
    new_cell     = cell_map.get(data.new_cell_id)
    old_cell_rec = cell_map.get(data.old_cell_id)

    if not new_cell:
        raise HTTPException(status_code=404, detail="Replacement Cell ID not found in inventory")
    if new_cell.is_used:
        raise HTTPException(status_code=400, detail="Replacement cell is already assigned to another pack")

    # New cell must also pass grading and sorting rules
    model = db.query(BatteryModel).filter(BatteryModel.model_id == battery.model_id).first()
    if model:
        cell_type = (
            model.cell_type.value if hasattr(model.cell_type, "value")
            else str(model.cell_type)
        ).upper()
        if cell_type == "NMC" and new_cell.sorting_date is None:
            raise HTTPException(
                status_code=400,
                detail="Replacement cell has no sorting data. NMC batteries require sorting before assembly."
            )

    if new_cell.status != "pass":
        raise HTTPException(
            status_code=400,
            detail=f"Replacement cell has not passed grading (status: {(new_cell.status or 'NOT GRADED').upper()})"
        )

    # Validate against assembly-time ranges stored on battery
    failures = _validate_cell_ranges(new_cell, battery)
    if failures:
        raise HTTPException(status_code=400, detail={
            "error":   "Replacement cell does not meet the assembly-time quality ranges",
            "details": failures
        })

    # Atomic swap
    try:
        db.delete(old_mapping)

        if old_cell_rec:
            old_cell_rec.is_used  = False
            old_cell_rec.status   = "ng"
            old_cell_rec.ng_count = (old_cell_rec.ng_count or 0) + 1

        db.add(BatteryCellMapping(battery_id=data.battery_id, cell_id=data.new_cell_id))
        new_cell.is_used      = True
        battery.had_ng_status = True

        db.commit()
        return {
            "status":  "Success",
            "message": f"Replaced {data.old_cell_id} → {data.new_cell_id} in {data.battery_id}"
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")