from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
import pandas as pd
import io

from app.database import get_db
from app.models.cell import Cell, CellGrading
from app.core.signals import trigger_dashboard_update

router = APIRouter(prefix="/cells", tags=["Cell Management"])


# ── Helper ────────────────────────────────────────────────────────────────────

def _clean_str(val) -> str | None:
    """
    Convert a value to a clean string, handling pandas float reads of
    integer Excel cells:

        101.0       → "101"
        4842231.0   → "4842231"
        "TEN POWER" → "TEN POWER"   (strings unchanged)
        NaN / None  → None

    Root cause: Excel stores Cell ID and Lot as numbers. pandas reads
    numeric columns as float64 by default, turning 101 into 101.0.
    astype(str) then gives "101.0" instead of "101".
    """
    if val is None:
        return None
    if isinstance(val, float):
        if pd.isna(val):
            return None
        # Whole-number float → strip decimal: 101.0 → "101"
        return str(int(val)) if val == int(val) else str(val)
    s = str(val).strip()
    return s if s and s.lower() != 'nan' else None


def _clean_cell_id_series(series: pd.Series) -> pd.Series:
    """
    Apply _clean_str logic to an entire pandas Series efficiently.
    Used to fix the Cell ID column before building cell_ids list.
    """
    return series.apply(lambda x: _clean_str(x) if pd.notna(x) else None)


# ── Page 1: Cell Grading Upload ───────────────────────────────────────────────

@router.post("/upload-grading")
async def upload_grading(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Upload grading report (CSV or Excel) — optimised for 40,000+ rows/day.

    Performance strategy:
    - 1 query  to fetch ALL matching Cell records at once
    - 1 query  to fetch ALL matching CellGrading records at once
    - All mutations happen in Python (in-memory)
    - 1 bulk INSERT for new Cell records
    - 1 bulk INSERT for new CellGrading records
    - 1 final commit
    Total: 3-5 DB round-trips regardless of file size.

    Business rules:
    - Auto-registers cell if not found in DB
    - Master Cell record locked once status = "pass" (no further overwrites)
    - ng_count incremented on every failed upload until cell passes
    - CellGrading detail record always upserted with latest data

    Summary counters are mutually exclusive:
    - auto_registered: brand new cell seen for the first time
    - updated:         existing cell whose master record was updated
    - skipped:         existing cell already at "pass" — master locked, detail still updated
    - errors:          rows that threw an exception
    """
    contents = await file.read()

    if file.filename.endswith(('.xlsx', '.xls')):
        df = pd.read_excel(io.BytesIO(contents))
    else:
        df = pd.read_csv(io.BytesIO(contents))

    df = df.dropna(subset=['Cell ID'])

    import numpy as np
    df = df.replace({pd.NA: None, np.nan: None})

    # FIX: use _clean_cell_id_series instead of plain astype(str).str.strip()
    # This converts 101.0 → "101" instead of "101.0"
    df['Cell ID'] = _clean_cell_id_series(df['Cell ID'])
    df = df[df['Cell ID'].notna()]   # drop any rows where cell_id became None

    # ── Validate required columns ─────────────────────────────────────────────
    required = ['Cell ID', 'final Result', 'Discharging Capacity(mAh)', 'Date']
    missing  = [c for c in required if c not in df.columns]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required columns in file: {', '.join(missing)}"
        )

    cell_ids = df['Cell ID'].tolist()

    # ── Bulk fetch — 1 query each ─────────────────────────────────────────────
    existing_cells    = db.query(Cell).filter(Cell.cell_id.in_(cell_ids)).all()
    existing_gradings = db.query(CellGrading).filter(CellGrading.cell_id.in_(cell_ids)).all()

    cell_map    = {c.cell_id: c for c in existing_cells}
    grading_map = {g.cell_id: g for g in existing_gradings}

    summary = {"auto_registered": 0, "updated": 0, "skipped": 0, "errors": 0}
    errors  = []

    new_cells    = []
    new_gradings = []

    for _, row in df.iterrows():
        try:
            cell_id = _clean_str(row['Cell ID'])
            if not cell_id:
                continue

            # ── Auto-register if not found ────────────────────────────────────
            cell        = cell_map.get(cell_id)
            is_new_cell = (cell is None)

            if is_new_cell:
                cell = Cell(cell_id=cell_id, is_used=False, status="pending", ng_count=0)
                new_cells.append(cell)
                cell_map[cell_id] = cell

            # ── Update master Cell record ─────────────────────────────────────
            already_passed = (cell.status == "pass")

            if already_passed:
                summary["skipped"] += 1

            else:
                is_pass = str(row.get('final Result', '')).strip().upper() == "PASS"

                if is_pass:
                    cell.status                   = "pass"
                    cell.discharging_capacity_mah = row.get('Discharging Capacity(mAh)')
                else:
                    cell.status    = "ng"
                    cell.ng_count  = (cell.ng_count or 0) + 1
                    cell.discharging_capacity_mah = row.get('Discharging Capacity(mAh)')

                cell.last_test_date = row.get('Date')

                if is_new_cell:
                    summary["auto_registered"] += 1
                else:
                    summary["updated"] += 1

            
            grading_data = {
                "test_date":                row.get('Date'),
                "lot":                      _clean_str(row.get('Lot')),
                "brand":                    _clean_str(row.get('Brand')),
                "specification":            _clean_str(row.get('Specification')),
                "ocv_voltage_mv":           row.get('OCV Voltage(mV)', 0),
                "upper_cutoff_mv":          row.get('Upper cut off(mV)', 0),
                "lower_cutoff_mv":          row.get('Lower cut off(mV)', 0),
                "discharging_capacity_mah": row.get('Discharging Capacity(mAh)', 0),
                "result":                   _clean_str(row.get('Result', '')),
                "final_soc_mah":            row.get('Final SOC(mAh)', 0),
                "soc_result":               _clean_str(row.get('SOC Result', '')), # FIXED PARENTHESES
                "final_cv_capacity":        row.get('Final CV Capacity', 0),
                "final_result":             _clean_str(row.get('final Result', '')),
            }

            existing_grading = grading_map.get(cell_id)
            if existing_grading:
                for k, v in grading_data.items():
                    setattr(existing_grading, k, v)
            else:
                new_grading = CellGrading(cell_id=cell_id, **grading_data)
                new_gradings.append(new_grading)
                grading_map[cell_id] = new_grading

        except Exception as e:
            summary["errors"] += 1
            errors.append({"cell_id": str(row.get('Cell ID', '?')), "reason": str(e)})

    # ── Bulk insert all new records — 1 operation each ────────────────────────
    if new_cells:
        db.bulk_save_objects(new_cells)
        db.flush()   # flush so new cell PKs exist before grading foreign keys insert

    if new_gradings:
        db.bulk_save_objects(new_gradings)

    try:
        db.commit()
        await trigger_dashboard_update()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return {"status": "Complete", "summary": summary, "errors": errors}


# ── Page 2: Cell Sorting Upload ───────────────────────────────────────────────

@router.post("/upload-sorting")
async def upload_sorting(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Upload sorting report (Excel) — optimised for 40,000+ rows/day.

    Performance strategy:
    - 1 query to fetch ALL matching Cell records at once
    - All mutations happen in Python (in-memory)
    - 1 final commit
    Total: 2 DB round-trips regardless of file size.

    Business rules:
    - Cell must have status "pass" before sorting data is written
    - Always overwrites with latest IR and voltage (re-sorting allowed)
    """
    contents = await file.read()
    df = pd.read_excel(io.BytesIO(contents))

    # FIX: same clean conversion for sorting file Cell IDs
    df['Cell ID'] = _clean_cell_id_series(df['Cell ID'])
    df = df[df['Cell ID'].notna()]

    # ── Validate required columns ─────────────────────────────────────────────
    required_columns = ['Cell ID', 'IR VALUE', 'VOLTAGE']
    missing_cols = [c for c in required_columns if c not in df.columns]
    if missing_cols:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required columns in file: {', '.join(missing_cols)}"
        )

    cell_ids = df['Cell ID'].tolist()

    # ── Bulk fetch — 1 query ──────────────────────────────────────────────────
    existing_cells = db.query(Cell).filter(Cell.cell_id.in_(cell_ids)).all()
    cell_map       = {c.cell_id: c for c in existing_cells}

    summary = {"sorted": 0, "not_graded": 0, "not_found": 0, "missing_data": 0, "errors": 0}
    errors  = []

    for _, row in df.iterrows():
        try:
            cell_id = _clean_str(row['Cell ID'])
            if not cell_id:
                continue

            cell = cell_map.get(cell_id)

            if not cell:
                summary["not_found"] += 1
                errors.append({"cell_id": cell_id, "reason": "Not found in database"})
                continue

            if cell.status != "pass":
                summary["not_graded"] += 1
                errors.append({
                    "cell_id": cell_id,
                    "reason": f"Cell has not passed grading (status: {cell.status.upper()})"
                })
                continue

            ir   = row.get('IR VALUE')
            volt = row.get('VOLTAGE')

            if ir is None or volt is None or (isinstance(ir, float) and pd.isna(ir)) or (isinstance(volt, float) and pd.isna(volt)):
                summary["missing_data"] += 1
                errors.append({
                    "cell_id": cell_id,
                    "reason": "IR VALUE or VOLTAGE is missing or empty in this row"
                })
                continue

            cell.ir_value_m_ohm  = float(ir)
            cell.sorting_voltage = float(volt)

            if row.get('Date') and not (isinstance(row.get('Date'), float) and pd.isna(row.get('Date'))):
                cell.sorting_date = row.get('Date')

            summary["sorted"] += 1

        except Exception as e:
            summary["errors"] += 1
            errors.append({"cell_id": str(row.get('Cell ID', '?')), "reason": str(e)})

    try:
        db.commit()
        await trigger_dashboard_update()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return {"status": "Sorting Updated", "summary": summary, "errors": errors}