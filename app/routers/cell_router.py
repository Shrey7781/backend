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
    df = pd.read_excel(io.BytesIO(contents)) if file.filename.endswith(('.xlsx','.xls')) else __import__('pandas').read_csv(__import__('io').BytesIO(contents))
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
            errors.append({"cell_id": str(row.get('Cell ID','?')), "reason": str(e)})

    db.commit()
    await trigger_dashboard_update()
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

    summary = {"sorted": 0, "not_graded": 0, "not_found": 0, "errors": 0}
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
        except Exception as e:
            summary["errors"] += 1
            errors.append({"cell_id": str(row.get('Cell ID','?')), "reason": str(e)})

    db.commit()
    return {"status": "Sorting Updated", "summary": summary, "errors": errors}