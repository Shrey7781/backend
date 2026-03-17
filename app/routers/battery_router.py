from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.battery import BatteryModel
from app.models.battery_pack import Battery
from app.schemas.battery_schema import BatteryModelCreate, BatteryModelResponse
from pydantic import BaseModel
from typing import Optional, List
import pandas as pd
import io

router = APIRouter(prefix="/battery-models", tags=["Battery Models"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class BatteryModelUpdate(BaseModel):
    """All fields optional — only provided fields are updated (PATCH semantics)."""
    category:       Optional[str] = None
    series_count:   Optional[int] = None
    parallel_count: Optional[int] = None
    cell_type:      Optional[str] = None   # "NMC" | "LFP"
    bms_model:      Optional[str] = None
    welding_type:   Optional[str] = None   # "LASER" | "SPOT"


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.post("/", response_model=BatteryModelResponse)
def create_battery_model(model: BatteryModelCreate, db: Session = Depends(get_db)):
    existing = db.query(BatteryModel).filter(BatteryModel.model_id == model.model_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Model ID already exists")
    new_model = BatteryModel(**model.model_dump())
    db.add(new_model)
    db.commit()
    db.refresh(new_model)
    return new_model


@router.get("/summary")
def get_battery_models_summary(db: Session = Depends(get_db)):
    models = db.query(
        BatteryModel.model_id,
        BatteryModel.category,
        BatteryModel.series_count,
        BatteryModel.parallel_count,
        BatteryModel.cell_type,
        BatteryModel.welding_type,
        BatteryModel.bms_model
    ).all()
    return [
        {
            "model_id":       m.model_id,
            "category":       m.category,
            "cell_type":      m.cell_type.value    if hasattr(m.cell_type,    'value') else m.cell_type,
            "welding_type":   m.welding_type.value if hasattr(m.welding_type, 'value') else m.welding_type,
            "bms_model":      m.bms_model,
            "total_count":    m.series_count * m.parallel_count,
            "series_count":   m.series_count,
            "parallel_count": m.parallel_count,
        }
        for m in models
    ]


@router.get("/by-battery/{battery_id}", response_model=BatteryModelResponse)
def get_model_by_battery_id(battery_id: str, db: Session = Depends(get_db)):
    result = db.query(BatteryModel) \
        .join(Battery, Battery.model_id == BatteryModel.model_id) \
        .filter(Battery.battery_id == battery_id) \
        .first()
    if not result:
        raise HTTPException(status_code=404, detail=f"No battery or model found for battery ID '{battery_id}'")
    return result


@router.get("/{model_id}", response_model=BatteryModelResponse)
def get_battery_model(model_id: str, db: Session = Depends(get_db)):
    db_model = db.query(BatteryModel).filter(BatteryModel.model_id == model_id).first()
    if not db_model:
        raise HTTPException(status_code=404, detail="Battery model not found")
    return db_model


@router.get("/{battery_id}/welding-info")
def get_welding_type(battery_id: str, db: Session = Depends(get_db)):
    result = db.query(Battery, BatteryModel.welding_type) \
        .join(BatteryModel, Battery.model_id == BatteryModel.model_id) \
        .filter(Battery.battery_id == battery_id) \
        .first()
    if not result:
        raise HTTPException(status_code=404, detail=f"Battery ID {battery_id} not found in system")
    _, welding_type = result
    return {
        "battery_id":   battery_id,
        "welding_type": welding_type.value if hasattr(welding_type, 'value') else welding_type,
    }


@router.patch("/{battery_id}/mark-ready")
def update_to_ready(battery_id: str, db: Session = Depends(get_db)):
    battery = db.query(Battery).filter(Battery.battery_id == battery_id).first()
    if not battery:
        raise HTTPException(status_code=404, detail="Battery not found")
    if battery.overall_status != "FG PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot mark as READY. Current status is {battery.overall_status}"
        )
    battery.overall_status = "READY TO DISPATCH"
    db.commit()
    return {"status": "success", "new_status": battery.overall_status}


@router.patch("/{model_id}/update", response_model=BatteryModelResponse)
def update_battery_model(
    model_id: str,
    updates:  BatteryModelUpdate,
    db:       Session = Depends(get_db)
):
    """
    Partially update a battery model. Only provided fields are changed.
    model_id is immutable (primary key).
    Blocks series/parallel changes if batteries are already linked.
    """
    db_model = db.query(BatteryModel).filter(BatteryModel.model_id == model_id).first()
    if not db_model:
        raise HTTPException(status_code=404, detail="Battery model not found")

    if updates.series_count is not None or updates.parallel_count is not None:
        linked_count = db.query(Battery).filter(Battery.model_id == model_id).count()
        if linked_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot change series/parallel — {linked_count} battery pack(s) already use this model"
            )

    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(db_model, field, value)

    db.commit()
    db.refresh(db_model)
    return db_model


@router.delete("/{model_id}")
def delete_battery_model(model_id: str, db: Session = Depends(get_db)):
    """Blocked if any Battery records reference this model."""
    db_model = db.query(BatteryModel).filter(BatteryModel.model_id == model_id).first()
    if not db_model:
        raise HTTPException(status_code=404, detail="Battery model not found")

    linked_count = db.query(Battery).filter(Battery.model_id == model_id).count()
    if linked_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete — {linked_count} battery pack(s) are linked to this model. "
                   f"Remove or reassign them first."
        )

    db.delete(db_model)
    db.commit()
    return {"status": "deleted", "model_id": model_id}


# ── Bulk Link ─────────────────────────────────────────────────────────────────

@router.post("/bulk-link")
async def bulk_link_batteries_to_models(
    file: UploadFile = File(...),
    db:   Session    = Depends(get_db)
):
    """
    Upload an Excel file with columns: battery_id, model_name.

    Performance:
      1 query  → all referenced BatteryModel records  (IN lookup)
      1 query  → all existing Battery records          (IN lookup)
      All validation in-memory — zero DB queries in the loop
      1 bulk insert + 1 commit

    Total: 3 DB round-trips regardless of file size.
    Previously: 2 queries × N rows.
    """
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Please upload an Excel file (.xlsx or .xls)")

    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read Excel file: {str(e)}")

    df.columns = df.columns.str.strip().str.lower()

    required_cols = {'battery_id', 'model_name'}
    missing = required_cols - set(df.columns)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required columns: {missing}. Found: {list(df.columns)}"
        )

    # ── Step 1: Parse and clean every row ────────────────────────────────────
    parsed_rows = []
    errors = []

    for idx, row in df.iterrows():
        battery_id = str(row['battery_id']).strip()
        model_name = str(row['model_name']).strip()

        if not battery_id or battery_id.lower() == 'nan':
            errors.append({"row": idx + 2, "reason": "Empty battery_id"})
            continue

        if not model_name or model_name.lower() == 'nan':
            errors.append({"row": idx + 2, "battery_id": battery_id, "reason": "Empty model_name"})
            continue

        parsed_rows.append((idx + 2, battery_id, model_name))

    # ── Step 2: Collect unique IDs for bulk fetch ─────────────────────────────
    all_model_names = list({mn  for _, _, mn  in parsed_rows})
    all_battery_ids = list({bid for _, bid, _ in parsed_rows})

    # ── Step 3: ONE query — all referenced models ─────────────────────────────
    models_in_db = db.query(BatteryModel.model_id).filter(
        BatteryModel.model_id.in_(all_model_names)
    ).all()
    model_set = {m.model_id for m in models_in_db}

    # ── Step 4: ONE query — all existing batteries ────────────────────────────
    existing_in_db = db.query(Battery.battery_id).filter(
        Battery.battery_id.in_(all_battery_ids)
    ).all()
    existing_set = {b.battery_id for b in existing_in_db}

    # ── Step 5: Validate + build new records in-memory (zero DB queries) ──────
    created       = []
    skipped       = []
    new_batteries = []
    seen_in_file  = set()   # guard against duplicate battery_ids within the file

    for row_num, battery_id, model_name in parsed_rows:

        # Model must exist
        if model_name not in model_set:
            errors.append({
                "row":        row_num,
                "battery_id": battery_id,
                "reason":     f"Model '{model_name}' not found in battery_models"
            })
            continue

        # Skip if already in DB
        if battery_id in existing_set:
            skipped.append(battery_id)
            continue

        # Skip duplicate rows within the same file
        if battery_id in seen_in_file:
            skipped.append(battery_id)
            continue

        new_batteries.append(Battery(battery_id=battery_id, model_id=model_name))
        seen_in_file.add(battery_id)
        created.append(battery_id)

    # ── Step 6: Bulk insert + single commit ───────────────────────────────────
    try:
        if new_batteries:
            db.bulk_save_objects(new_batteries)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return {
        "status": "Complete",
        "summary": {
            "total_rows": len(df),
            "created":    len(created),
            "skipped":    len(skipped),
            "errors":     len(errors),
        },
        "created_batteries": created,
        "skipped_batteries": skipped,
        "errors":            errors,
    }