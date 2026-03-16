import pandas as pd
import io
import numpy as np
from typing import List
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.pdi import PDIReport
from app.models.battery_pack import Battery
from app.core.signals import trigger_dashboard_update

router = APIRouter(prefix="/pdi", tags=["Pre-Delivery Inspection"])


# ── Page 8: PDI Inspection Batch Upload ──────────────────────────────────────

@router.post("/upload-batch")
async def upload_batch_pdi(
    files: List[UploadFile] = File(...),
    db:    Session          = Depends(get_db)
):
    """
    Upload 1–200 PDI Excel files in one request.

    Performance strategy:
    - Parse ALL files first, collect every battery_id mentioned
    - ONE bulk query to fetch all matching Battery records
    - ONE bulk query to fetch all existing PDIReport records
    - All mutations in-memory (no DB queries inside any loop)
    - ONE commit at the end for all files combined

    Total DB round-trips: 3 regardless of how many files or rows.

    Business rules:
    - Battery must already exist (registered via bulk-link)
    - "Finished PASS" → battery.overall_status = "FG PENDING"
    - Any other result → battery.overall_status = "FAILED", had_ng_status = True
    - PDI record: always overwrite with latest data (re-test allowed)
    """

    # ── Step 1: Parse all files, collect rows and battery IDs ─────────────────
    parsed_rows = []   # list of (filename, bid, row_dict)
    file_errors = []   # errors at file-read level (unreadable files etc.)

    for file in files:
        try:
            contents = await file.read()
            df = pd.read_excel(io.BytesIO(contents))
            df = df.replace({np.nan: None})
            df.columns = df.columns.str.strip()

            # Validate required columns exist in this file
            if 'Internal SN' not in df.columns:
                file_errors.append({
                    "file":   file.filename,
                    "reason": "Missing required column: 'Internal SN'"
                })
                continue

            if 'Test Result' not in df.columns:
                file_errors.append({
                    "file":   file.filename,
                    "reason": "Missing required column: 'Test Result'"
                })
                continue

            for _, row in df.iterrows():
                raw_id = row.get('Internal SN')

                # Skip rows where battery ID is missing or NaN
                if raw_id is None or str(raw_id).strip() in ('', 'None', 'nan'):
                    continue

                bid = str(raw_id).strip()
                parsed_rows.append((file.filename, bid, row.to_dict()))

        except Exception as e:
            file_errors.append({"file": file.filename, "reason": str(e)})

    if not parsed_rows and file_errors:
        # All files failed to parse — return early, nothing to commit
        raise HTTPException(status_code=400, detail={
            "message": "All uploaded files failed to parse.",
            "errors":  file_errors
        })

    # ── Step 2: Collect all unique battery IDs from all files ─────────────────
    all_battery_ids = list({bid for _, bid, _ in parsed_rows})

    # ── Step 3: ONE bulk query for batteries ──────────────────────────────────
    batteries    = db.query(Battery).filter(Battery.battery_id.in_(all_battery_ids)).all()
    battery_map  = {b.battery_id: b for b in batteries}

    # ── Step 4: ONE bulk query for existing PDI reports ───────────────────────
    pdi_reports  = db.query(PDIReport).filter(PDIReport.battery_id.in_(all_battery_ids)).all()
    pdi_map      = {p.battery_id: p for p in pdi_reports}

    # ── Step 5: Process all rows in-memory — zero DB queries in this loop ─────
    summary = {"created": [], "updated": [], "errors": []}
    new_reports = []

    for filename, bid, row in parsed_rows:

        # Battery must exist
        battery = battery_map.get(bid)
        if not battery:
            summary["errors"].append({
                "file":   filename,
                "id":     bid,
                "reason": "Battery not registered in system"
            })
            continue

        result_text = str(row.get('Test Result', '') or '').strip()

        # Update battery status based on test result
        if result_text == "Finished PASS":
            battery.overall_status = "FG PENDING"
        else:
            battery.overall_status = "FAILED"
            battery.had_ng_status  = True   # NG flag persists forever

        # Build the PDI field values
        pdi_fields = {
            "test_time":                  row.get('Time'),
            "voltage_v":                  row.get('Voltage(V)'),
            "resistance_m_ohm":           row.get('Resistance(m¦¸)'),
            "cont_charging_current":      row.get('Continuous Charging Current(A)'),
            "cont_charging_voltage":      row.get('Continuous Charging Voltage(V)'),
            "cont_discharging_current":   row.get('Continuous Discharging Current(A)'),
            "cont_discharging_voltage":   row.get('Continuous Discharging Voltage(V)'),
            "short_circuit_prot_time_us": row.get('Short circuit protection time (uS)'),
            "test_result":                result_text or "Unknown",
        }

        existing = pdi_map.get(bid)
        if existing:
            # Update existing record in-place
            for k, v in pdi_fields.items():
                setattr(existing, k, v)
            summary["updated"].append(bid)
        else:
            # Create new record — add to bulk insert list
            new_report = PDIReport(battery_id=bid, **pdi_fields)
            new_reports.append(new_report)
            pdi_map[bid] = new_report   # prevent duplicate creation if bid appears in multiple files
            summary["created"].append(bid)

    # ── Step 6: Bulk insert new records + single commit ───────────────────────
    try:
        if new_reports:
            db.bulk_save_objects(new_reports)

        db.commit()
        await trigger_dashboard_update()

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error during commit: {str(e)}")

    return {
        "status": "Process Complete",
        "stats": {
            "total_files":         len(files),
            "total_rows_processed": len(parsed_rows),
            "new_entries":         len(summary["created"]),
            "overwritten_entries": len(summary["updated"]),
            "failed":              len(summary["errors"]) + len(file_errors),
        },
        "row_errors":  summary["errors"],   # individual row-level errors
        "file_errors": file_errors,          # file-level parse errors
    }