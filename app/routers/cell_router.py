from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
import pandas as pd
import io
from app.database import get_db
from app.models.cell import Cell, CellGrading
from app.services.cell_service import update_cell_grading_logic, update_sorting_data


router = APIRouter(prefix="/cells", tags=["Cell Management"])

@router.post("/register/{cell_id}")
def register_cell(cell_id: str, db: Session = Depends(get_db)):
    # Check if cell exists
    existing = db.query(Cell).filter(Cell.cell_id == cell_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Cell ID already exists")
    
    new_cell = Cell(cell_id=cell_id, is_used=False)
    db.add(new_cell)
    db.commit()
    db.refresh(new_cell) 
    return {"message": "Cell registered successfully", "cell": new_cell.cell_id}

@router.get("/recent-registrations")
def get_recent_cells(db: Session = Depends(get_db)):
    recent_cells = db.query(Cell.cell_id, Cell.registration_date).order_by(Cell.registration_date.desc()).limit(5).all()
    return [{"cell_id": cell.cell_id, "registration_date": cell.registration_date} for cell in recent_cells]

@router.post("/upload-grading")
async def upload_grading(file: UploadFile = File(...), db: Session = Depends(get_db)):
    contents = await file.read()
    
    # Robust file reading (handles both CSV and Excel)
    if file.filename.endswith(('.xlsx', '.xls')):
        df = pd.read_excel(io.BytesIO(contents))
    else:
        df = pd.read_csv(io.BytesIO(contents))

    # Clean data: Remove rows where Cell ID is missing
    df = df.dropna(subset=['Cell ID'])

    summary = {"success": 0, "skipped": 0, "errors": 0}

    for _, row in df.iterrows():
        cell_id = str(row['Cell ID']).strip()
        cell = db.query(Cell).filter(Cell.cell_id == cell_id).first()
        
        if not cell:
            summary["errors"] += 1
            continue

        # Convert row to dict for the service
        action = update_cell_grading_logic(db, cell, row.to_dict())
        
        if action == "skipped":
            summary["skipped"] += 1
        else:
            summary["success"] += 1

    db.commit()
    return {"status": "Complete", "summary": summary}

@router.post("/upload-sorting")
async def upload_sorting(file: UploadFile = File(...), db: Session = Depends(get_db)):
    contents = await file.read()
    df = pd.read_excel(io.BytesIO(contents)) # Matches your 'sorting report.xlsx'

    summary = {"success": 0, "errors": 0, "not_graded": 0}

    for _, row in df.iterrows():
        cell_id = str(row['Cell ID'])
        cell = db.query(Cell).filter(Cell.cell_id == cell_id).first()
        
        if not cell:
            summary["errors"] += 1
            continue
            
        # Apply sorting update
        result = update_sorting_data(db, cell, row.to_dict())
        
        if result == "sorted":
            summary["success"] += 1
        elif result == "error_not_passed":
            summary["not_graded"] += 1

    db.commit()
    return {"status": "Sorting Updated", "summary": summary}