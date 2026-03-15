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


# ── Schemas ──────────────────────────────────────────────────────────────────

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
    Check cell parameters against whatever ranges are stored on the Battery
    record (set at assembly time). A parameter is only checked when BOTH its
    lower and upper bounds are not None.

    Returns None if the cell passes all provided checks, or a dict describing
    the failure if it doesn't.
    """
    failures = {}

    if battery.cell_ir_lower is not None and battery.cell_ir_upper is not None:
        if cell.ir_value_m_ohm is None or not (
            battery.cell_ir_lower <= cell.ir_value_m_ohm <= battery.cell_ir_upper
        ):
            failures["ir"] = {
                "actual": cell.ir_value_m_ohm,
                "expected": f"{battery.cell_ir_lower}–{battery.cell_ir_upper} mΩ"
            }

    if battery.cell_voltage_lower is not None and battery.cell_voltage_upper is not None:
        if cell.sorting_voltage is None or not (
            battery.cell_voltage_lower <= cell.sorting_voltage <= battery.cell_voltage_upper
        ):
            failures["voltage"] = {
                "actual": cell.sorting_voltage,
                "expected": f"{battery.cell_voltage_lower}–{battery.cell_voltage_upper} V"
            }

    if battery.cell_capacity_lower is not None and battery.cell_capacity_upper is not None:
        if cell.discharging_capacity_mah is None or not (
            battery.cell_capacity_lower <= cell.discharging_capacity_mah <= battery.cell_capacity_upper
        ):
            failures["capacity"] = {
                "actual": cell.discharging_capacity_mah,
                "expected": f"{battery.cell_capacity_lower}–{battery.cell_capacity_upper} mAh"
            }

    return failures if failures else None


# ── Range-window rules per cell chemistry ─────────────────────────────────────
#
#   NMC:  capacity fixed 1035–1040 mAh  |  IR window ≤ 0.20 mΩ  |  voltage window ≤ 0.005 V
#   LFP:  capacity window ≤ 0.5 mAh     |  IR window ≤ 0.04 mΩ  |  voltage window ≤ 0.004 V
#
# These are checked when the operator submits ranges at assembly time,
# BEFORE any cell values are validated.

_RANGE_RULES = {
    # NMC: IR window ≤ 0.20 mΩ | voltage window ≤ 0.005 V | capacity window ≤ 5 mAh (no fixed band)
    "NMC": {
        "ir_max_window":       0.20,
        "voltage_max_window":  0.005,
        "capacity_max_window": 5.0,
    },
    # LFP: IR window ≤ 0.04 mΩ | voltage window ≤ 0.004 V | capacity window ≤ 0.5 mAh
    "LFP": {
        "ir_max_window":       0.04,
        "voltage_max_window":  0.004,
        "capacity_max_window": 0.5,
    },
}

def _validate_range_windows(data: "AssignCellsRequest", cell_type: str) -> list[str]:
    """
    Validate that the operator-supplied ranges themselves are within allowed
    tolerances for the given cell chemistry.  Returns a list of error strings
    (empty = all good).
    """
    errors = []
    rules  = _RANGE_RULES.get(cell_type.upper())
    if not rules:
        return errors   # unknown chemistry — skip check

    # ── IR window ──────────────────────────────────────────────────────────
    if data.cell_ir_lower is not None and data.cell_ir_upper is not None:
        if data.cell_ir_upper < data.cell_ir_lower:
            errors.append("IR: upper bound must be ≥ lower bound")
        else:
            window = round(data.cell_ir_upper - data.cell_ir_lower, 6)
            max_w  = rules["ir_max_window"]
            if window > max_w:
                errors.append(
                    f"IR range window is {window} mΩ — "
                    f"maximum allowed for {cell_type} is {max_w} mΩ"
                )

    # ── Voltage window ─────────────────────────────────────────────────────
    if data.cell_voltage_lower is not None and data.cell_voltage_upper is not None:
        if data.cell_voltage_upper < data.cell_voltage_lower:
            errors.append("Voltage: upper bound must be ≥ lower bound")
        else:
            window = round(data.cell_voltage_upper - data.cell_voltage_lower, 6)
            max_w  = rules["voltage_max_window"]
            if window > max_w:
                errors.append(
                    f"Voltage range window is {window} V — "
                    f"maximum allowed for {cell_type} is {max_w} V"
                )

    # ── Capacity window — same sliding-window logic for both NMC and LFP ────
    if data.cell_capacity_lower is not None and data.cell_capacity_upper is not None:
        if data.cell_capacity_upper < data.cell_capacity_lower:
            errors.append("Capacity: upper bound must be ≥ lower bound")
        elif rules.get("capacity_max_window") is not None:
            window = round(data.cell_capacity_upper - data.cell_capacity_lower, 6)
            max_w  = rules["capacity_max_window"]
            if window > max_w:
                errors.append(
                    f"Capacity range window is {window} mAh — "
                    f"maximum allowed for {cell_type} is {max_w} mAh"
                )

    return errors


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/assign-cells")
async def assign_cells_to_battery(
    data: AssignCellsRequest,
    db: Session = Depends(get_db)
):
    """
    Scan a battery ID and a list of cell IDs.
    Optionally provide IR / voltage / capacity ranges — only the ranges that
    have BOTH lower and upper bounds will be validated.  If no ranges are
    provided at all, cells pass automatically (no parameter check).

    The ranges supplied here are saved permanently on the Battery record for
    the audit trail.
    """
    # 1. Fetch battery
    battery = db.query(Battery).filter(Battery.battery_id == data.battery_id).first()
    if not battery:
        raise HTTPException(status_code=404, detail="Battery ID not found. Use /bulk-import first.")

    # 2. Validate range windows against cell chemistry rules BEFORE saving anything
    model = db.query(BatteryModel).filter(BatteryModel.model_id == battery.model_id).first()
    if model:
        range_errors = _validate_range_windows(data, model.cell_type.value)
        if range_errors:
            raise HTTPException(status_code=422, detail={
                "error":       "Supplied ranges violate cell chemistry tolerances",
                "cell_type":   model.cell_type.value,
                "violations":  range_errors
            })

    # 4. Persist the ranges entered this session onto the Battery record
    #    (overwrites any previously stored ranges — last assembly wins)
    battery.cell_ir_lower       = data.cell_ir_lower
    battery.cell_ir_upper       = data.cell_ir_upper
    battery.cell_voltage_lower  = data.cell_voltage_lower
    battery.cell_voltage_upper  = data.cell_voltage_upper
    battery.cell_capacity_lower = data.cell_capacity_lower
    battery.cell_capacity_upper = data.cell_capacity_upper

    invalid_cells = []
    valid_mappings = []
    cells_to_mark  = []

    # 5. Validate each cell
    for cid in data.cell_ids:
        cell = db.query(Cell).filter(Cell.cell_id == cid).first()

        if not cell:
            invalid_cells.append({"cell_id": cid, "reason": "Cell ID not registered in inventory"})
            continue

        if cell.is_used:
            invalid_cells.append({"cell_id": cid, "reason": "Cell already assigned to another pack"})
            continue

        # Parameter range checks (only for ranges that were provided)
        failures = _validate_cell_ranges(cell, battery)
        if failures:
            invalid_cells.append({
                "cell_id": cid,
                "reason":  "Parameter out of range",
                "details": failures
            })
        else:
            valid_mappings.append(BatteryCellMapping(battery_id=data.battery_id, cell_id=cid))
            cells_to_mark.append(cell)

    # 6. Atomic — reject everything if any cell fails
    if invalid_cells:
        # Roll back the range save too since we're not committing
        db.rollback()
        return {
            "status":        "Error",
            "message":       "Validation failed — no cells were assigned",
            "invalid_cells": invalid_cells
        }

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
            "ir":       f"{data.cell_ir_lower}–{data.cell_ir_upper} mΩ"       if data.cell_ir_lower       is not None else None,
            "voltage":  f"{data.cell_voltage_lower}–{data.cell_voltage_upper} V"  if data.cell_voltage_lower  is not None else None,
            "capacity": f"{data.cell_capacity_lower}–{data.cell_capacity_upper} mAh" if data.cell_capacity_lower is not None else None,
        }.items() if v is not None
    }

    return {
        "status":        "Success",
        "message":       f"Assigned {len(valid_mappings)} cells to {data.battery_id}",
        "ranges_applied": ranges_applied or "None — all cells accepted without parameter checks"
    }


@router.post("/upload-report")
async def upload_pack_report_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Please upload an Excel file (.xlsx or .xls)")

    try:
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))
        df.columns = df.columns.str.strip()

        skipped_batteries  = []
        ng_marked          = []
        passed_and_updated = []

        for _, row in df.iterrows():
            bid = str(row['Barcode']).strip()

            battery = db.query(Battery).filter(Battery.battery_id == bid).first()
            if not battery:
                skipped_batteries.append(bid)
                continue

            current_status = str(row['final Result']).strip().upper()

            if current_status == "FAIL":
                battery.had_ng_status = True
                ng_marked.append(bid)
            elif current_status == "PASS":
                passed_and_updated.append(bid)

            report = db.query(PackTest).filter(PackTest.battery_id == bid).first()

            if report:
                report.test_date           = row['Date']
                report.specification       = str(row['Specification'])
                report.cell_type           = str(row['Cell type'])
                report.number_of_series    = int(row['Number of sreies'])
                report.number_of_parallel  = int(row['Number of parallel'])
                report.ocv_voltage         = float(row['OCV Voltage(V)'])
                report.upper_cutoff        = float(row['Upper cut off(V)'])
                report.lower_cutoff        = float(row['Lower cut off(V)'])
                report.discharging_capacity= float(row['Discharging Capacity(Ah)'])
                report.capacity_result     = str(row['Result'])
                report.idle_difference     = float(row['Final idle Different'])
                report.soc_result          = str(row['SOC Result'])
                report.final_voltage       = float(row['Final Voltage'])
                report.final_result        = current_status
            else:
                new_report = PackTest(
                    battery_id=bid,
                    test_date=row['Date'],
                    specification=str(row['Specification']),
                    cell_type=str(row['Cell type']),
                    number_of_series=int(row['Number of sreies']),
                    number_of_parallel=int(row['Number of parallel']),
                    ocv_voltage=float(row['OCV Voltage(V)']),
                    upper_cutoff=float(row['Upper cut off(V)']),
                    lower_cutoff=float(row['Lower cut off(V)']),
                    discharging_capacity=float(row['Discharging Capacity(Ah)']),
                    capacity_result=str(row['Result']),
                    idle_difference=float(row['Final idle Different']),
                    soc_result=str(row['SOC Result']),
                    final_voltage=float(row['Final Voltage']),
                    final_result=current_status
                )
                db.add(new_report)

        db.commit()
        await trigger_dashboard_update()

        return {
            "status": "Success",
            "summary": {
                "total_rows":              len(df),
                "processed":               len(ng_marked) + len(passed_and_updated),
                "marked_as_ng":            len(ng_marked),
                "passed_and_updated":      len(passed_and_updated),
                "skipped_unregistered":    skipped_batteries
            }
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error processing Excel: {str(e)}")


@router.post("/replace-cell")
async def replace_leaked_cell(
    data: ReplaceCellRequest,
    db: Session = Depends(get_db)
):
    # 1. Fetch Battery
    battery = db.query(Battery).filter(Battery.battery_id == data.battery_id).first()
    if not battery:
        raise HTTPException(status_code=404, detail="Battery Serial Number not found")

    # 2. Verify old cell is in this battery
    old_mapping = db.query(BatteryCellMapping).filter(
        BatteryCellMapping.battery_id == data.battery_id,
        BatteryCellMapping.cell_id    == data.old_cell_id
    ).first()
    if not old_mapping:
        raise HTTPException(status_code=404, detail="Old cell is not linked to this battery")

    # 3. Fetch new replacement cell
    new_cell = db.query(Cell).filter(Cell.cell_id == data.new_cell_id).first()
    if not new_cell:
        raise HTTPException(status_code=404, detail="Replacement Cell ID not found in inventory")
    if new_cell.is_used:
        raise HTTPException(status_code=400, detail="Replacement cell is already assigned to another pack")

    # 4. Validate against the ranges that were stored on the battery at assembly time.
    #    Uses the same helper — respects optional ranges.
    failures = _validate_cell_ranges(new_cell, battery)
    if failures:
        raise HTTPException(status_code=400, detail={
            "error":   "Replacement cell does not meet the assembly-time quality ranges",
            "details": failures
        })

    # 5. Atomic swap
    try:
        db.delete(old_mapping)

        old_cell_record = db.query(Cell).filter(Cell.cell_id == data.old_cell_id).first()
        if old_cell_record:
            old_cell_record.is_used  = False
            old_cell_record.status   = "NG"
            old_cell_record.ng_count += 1

        new_mapping = BatteryCellMapping(battery_id=data.battery_id, cell_id=data.new_cell_id)
        db.add(new_mapping)
        new_cell.is_used       = True
        battery.had_ng_status  = True

        db.commit()
        return {
            "status":  "Success",
            "message": f"Replaced {data.old_cell_id} → {data.new_cell_id} in {data.battery_id}"
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")