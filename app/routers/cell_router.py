from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
import pandas as pd
import io
from app.database import get_db
from app.models.cell import Cell
from app.services.cell_service import update_cell_grading_logic, update_sorting_data
from app.core.signals import trigger_dashboard_update

router = APIRouter(prefix="/cells", tags=["Cell Management"])


# ── Page 1: Cell Grading File Upload ─────────────────────────────────────────

@router.post("/upload-grading")
async def upload_grading(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Upload grading report (CSV or Excel).
    - Auto-registers cell if not found.
    - Master locked once status = pass; grading detail always updated.
    - ng_count incremented on every failed upload until cell passes.
    """
    contents = await file.read()

    # FIX #1 — removed __import__ hack, pd and io are already imported
    if file.filename.endswith(('.xlsx', '.xls')):
        df = pd.read_excel(io.BytesIO(contents))
    else:
        df = pd.read_csv(io.BytesIO(contents))

    df = df.dropna(subset=['Cell ID'])

    summary = {"auto_registered": 0, "updated": 0, "skipped": 0, "errors": 0}
    errors  = []

    for _, row in df.iterrows():
        try:
            cell_id = str(row['Cell ID']).strip()
            cell    = db.query(Cell).filter(Cell.cell_id == cell_id).first()

            if not cell:
                cell = Cell(cell_id=cell_id, is_used=False)
                db.add(cell)
                db.flush()
                summary["auto_registered"] += 1

            action = update_cell_grading_logic(db, cell, row.to_dict())
            summary["skipped" if action == "skipped" else "updated"] += 1

        except Exception as e:
            summary["errors"] += 1
            errors.append({"cell_id": str(row.get('Cell ID', '?')), "reason": str(e)})

    # FIX #4 — wrap final commit with error handling
    try:
        db.commit()
        await trigger_dashboard_update()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return {"status": "Complete", "summary": summary, "errors": errors}


# ── Page 2: Cell Sorting File Upload ─────────────────────────────────────────

@router.post("/upload-sorting")
async def upload_sorting(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Upload sorting report (Excel) — writes IR and voltage to passed cells.
    Always overwrites with latest sorting values. Re-sorting allowed.
    """
    contents = await file.read()
    df       = pd.read_excel(io.BytesIO(contents))

    # FIX #9 — validate required columns exist before processing
    required_columns = ['Cell ID', 'IR VALUE', 'VOLTAGE']
    missing_cols = [c for c in required_columns if c not in df.columns]
    if missing_cols:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required columns in file: {', '.join(missing_cols)}"
        )

    summary = {"sorted": 0, "not_graded": 0, "not_found": 0, "missing_data": 0, "errors": 0}
    errors  = []

    for _, row in df.iterrows():
        try:
            cell_id = str(row['Cell ID']).strip()
            cell    = db.query(Cell).filter(Cell.cell_id == cell_id).first()

            if not cell:
                summary["not_found"] += 1
                errors.append({"cell_id": cell_id, "reason": "Not found in database"})
                continue

            result = update_sorting_data(db, cell, row.to_dict())

            if result == "sorted":
                summary["sorted"] += 1
            elif result == "error_not_passed":
                summary["not_graded"] += 1
                errors.append({"cell_id": cell_id, "reason": "Cell has not passed grading yet"})
            elif result == "missing_data":
                # FIX #9 — handle missing IR VALUE or VOLTAGE in a specific row
                summary["missing_data"] += 1
                errors.append({"cell_id": cell_id, "reason": "IR VALUE or VOLTAGE missing in this row"})

        except Exception as e:
            summary["errors"] += 1
            errors.append({"cell_id": str(row.get('Cell ID', '?')), "reason": str(e)})

    # FIX #3 — added missing trigger_dashboard_update
    # FIX #4 — wrap final commit with error handling
    try:
        db.commit()
        await trigger_dashboard_update()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return {"status": "Sorting Updated", "summary": summary, "errors": errors}