import asyncio
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, case, literal_column, desc

import traceback
from typing import List

from sqlalchemy import or_
from datetime import datetime, date
from typing import Optional
from app.database import get_db

from app.database import get_db, SessionLocal
from app.models.cell import Cell
from app.models.battery_pack import Battery
from app.models.pdi import PDIReport
from app.models.dispatch import Dispatch
from app.models.pack_test import PackTest
from app.models.bms import BMS
from app.models.battery import BatteryModel

from app.models.cell import Cell, CellGrading
from app.models.battery_pack import BatteryCellMapping

router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])


# ── WebSocket Connection Manager ──────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, data: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()


# ── Dashboard Stats ───────────────────────────────────────────────────────────

async def fetch_dashboard_stats(db: Session):
    today = datetime.now().date()

    total_cells     = db.query(func.count(Cell.cell_id)).scalar() or 0
    batteries_count = db.query(func.count(Battery.battery_id)).scalar() or 0

    pdi_total  = db.query(func.count(PDIReport.id)).scalar() or 0
    pdi_passed = db.query(func.count(PDIReport.id)).filter(PDIReport.test_result == 'Finished PASS').scalar() or 0
    pass_rate  = f"{(pdi_passed / pdi_total * 100):.1f}%" if pdi_total > 0 else "0%"

    dispatched_today = db.query(func.count(Dispatch.id)).filter(
        func.date(Dispatch.dispatch_timestamp) == today
    ).scalar() or 0

    failed_packs = db.query(func.count(Battery.battery_id)).filter(
        Battery.had_ng_status == True
    ).scalar() or 0

    pending_pdi = db.query(func.count(Battery.battery_id)).outerjoin(PDIReport).filter(
        PDIReport.id == None
    ).scalar() or 0

    recent_pdi = db.query(
        PDIReport.battery_id.label("id"),
        literal_column("'PDI Inspection'").label("action"),
        PDIReport.created_at.label("time"),
        PDIReport.test_result.label("status")
    ).order_by(PDIReport.created_at.desc()).limit(5).all()

    today_output_query = db.query(
        Battery.battery_id,
        Battery.model_id.label("model"),
        literal_column("'Final Assembly'").label("stage"),
        case((Battery.had_ng_status == True, "REPAIRED"), else_="HEALTHY").label("status"),
        Battery.created_at.label("updated_at")
    ).filter(func.date(Battery.created_at) == today).all()

    return {
        "kpis": {
            "total_cells":         {"value": str(total_cells),     "change": "Total Inventory"},
            "batteries_assembled": {"value": str(batteries_count), "change": "Units"},
            "pdi_pass_rate":       {"value": pass_rate,            "change": "Quality Score"},
            "dispatched_today":    {"value": str(dispatched_today),"change": "Today"},
            "failed_batteries":    {"value": str(failed_packs),    "change": "Requires Check"},
            "pending_inspection":  {"value": str(pending_pdi),     "change": "Queue"}
        },
        "recent_activity": [
            {
                "time":   a.time.strftime("%H:%M") if a.time else "Now",
                "action": a.action,
                "id":     a.id,
                "status": "SUCCESS" if a.status == "Finished PASS" else "ERROR"
            }
            for a in recent_pdi
        ],
        "stage_breakdown": [
            {"stage": "Cell Registration", "count": total_cells,     "status": "ACTIVE"},
            {"stage": "Assembly",          "count": batteries_count, "status": "ACTIVE"},
            {"stage": "Dispatch Today",    "count": dispatched_today,"status": "COMPLETED"}
        ],
        "today_output": [
            {
                "battery_id": b.battery_id,
                "model":      b.model,
                "stage":      b.stage,
                "status":     b.status,
                "updated_at": b.updated_at.strftime("%H:%M") if b.updated_at else "Today"
            }
            for b in today_output_query
        ]
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/dashboard")
async def get_admin_dashboard(db: Session = Depends(get_db)):
    try:
        data = await fetch_dashboard_stats(db)
        return {"success": True, "data": data}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Dashboard calculation failed")


@router.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket, token: Optional[str] = Query(None)):
    await manager.connect(websocket)
    try:
        while True:
            with SessionLocal() as db:
                data = await fetch_dashboard_stats(db)
                await websocket.send_json({"success": True, "data": data})
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WS Error: {e}")
        manager.disconnect(websocket)


@router.get("/cells/inventory")
async def get_cell_inventory(
    page:      int            = Query(1, ge=1),
    page_size: int            = Query(20, ge=1),
    cell_id:   Optional[str]  = None,
    status:    Optional[str]  = None,
    brand:     Optional[str]  = None,   # renamed from 'model' — matches what it actually filters
    date_from: Optional[date] = None,
    date_to:   Optional[date] = None,
    db: Session = Depends(get_db)
):
    """
    Paginated cell inventory with filtering.

    Fixes applied:
    1. Query is on Cell only — CellGrading fetched separately per page via
       joinedload so no duplicate rows from outerjoin.
    2. Status filtering uses Cell.status (reliable) not CellGrading.final_result.
    3. grading accessed as item.gradings safely (handles empty list and None).
    4. Added distinct() guard on brand filter which uses a join.
    """
    try:
        # ── Build base query on Cell only ─────────────────────────────────────
        query = db.query(Cell)

        # Filter by cell_id (partial match)
        if cell_id:
            query = query.filter(Cell.cell_id.ilike(f"%{cell_id}%"))

        # Filter by registration date
        if date_from:
            query = query.filter(func.date(Cell.registration_date) >= date_from)
        if date_to:
            query = query.filter(func.date(Cell.registration_date) <= date_to)

        # FIX — status filter uses Cell.status (set by grading upload) not CellGrading.final_result
        if status:
            s = status.upper()
            if s == "ASSIGNED":
                query = query.filter(Cell.is_used == True)
            elif s == "GRADED":
                # graded = passed grading, not yet assigned
                query = query.filter(Cell.status == "pass", Cell.is_used == False)
            elif s == "FAILED":
                query = query.filter(Cell.status == "ng")
            elif s == "REGISTERED":
                # registered but no grading data yet
                query = query.filter(Cell.status == "pending")
            elif s == "SORTED":
                # passed grading AND has sorting data
                query = query.filter(Cell.status == "pass", Cell.sorting_date.isnot(None))

        # FIX — brand filter: join CellGrading only when needed, add distinct()
        if brand:
            query = (
                query
                .join(CellGrading, Cell.cell_id == CellGrading.cell_id, isouter=True)
                .filter(CellGrading.brand.ilike(f"%{brand}%"))
                .distinct()
            )

        # ── Paginate ──────────────────────────────────────────────────────────
        total_items = query.count()
        total_pages = (total_items + page_size - 1) // page_size
        offset      = (page - 1) * page_size

        # FIX — use joinedload so grading data loads in 1 extra query, not N queries
        # Also avoids the duplicate-row problem that outerjoin caused
        items = (
            query
            .options(joinedload(Cell.gradings))
            .order_by(Cell.registration_date.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )

        formatted_items = []
        for item in items:
            # Handle both list and single-object relationship return
            # (depends on uselist setting and SQLAlchemy version behaviour)
            raw = item.gradings
            if raw is None:
                grading = None
            elif isinstance(raw, list):
                grading = raw[0] if raw else None
            else:
                # uselist=False or joinedload returned single object directly
                grading = raw

            # Derive display status from Cell.status + is_used
            if item.is_used:
                current_status = "ASSIGNED"
            elif item.status == "pass" and item.sorting_date:
                current_status = "SORTED"
            elif item.status == "pass":
                current_status = "GRADED"
            elif item.status == "ng":
                current_status = "FAILED"
            else:
                current_status = "REGISTERED"

            formatted_items.append({
                "cell_id":         item.cell_id,
                "brand":           grading.brand            if grading else None,
                "status":          current_status,
                "grading_status":  item.status,             # raw: pending | ng | pass
                "ng_count":        item.ng_count,
                "registered_at":   item.registration_date.isoformat() if item.registration_date else None,
                "last_test_date":  item.last_test_date.isoformat()    if item.last_test_date    else None,
                "sorting_date":    item.sorting_date.isoformat()      if item.sorting_date      else None,
                "ir":              item.ir_value_m_ohm,
                "voltage":         item.sorting_voltage,
                "capacity":        item.discharging_capacity_mah,
                # Grading detail fields (None if not yet graded)
                "lot":             grading.lot              if grading else None,
                "specification":   grading.specification    if grading else None,
                "ocv_voltage_mv":  grading.ocv_voltage_mv   if grading else None,
                "final_result":    grading.final_result     if grading else None,
            })

        return {
            "success": True,
            "data": {
                "items":        formatted_items,
                "total_items":  total_items,
                "total_pages":  total_pages,
                "current_page": page
            }
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/traceability")
async def get_battery_traceability(
    page:       int            = Query(1, ge=1),
    page_size:  int            = Query(15, ge=1),
    battery_id: Optional[str]  = None,
    status:     Optional[str]  = None,
    date_from:  Optional[date] = None,
    date_to:    Optional[date] = None,
    db: Session = Depends(get_db)
):
    try:
        query = db.query(Battery).options(
            joinedload(Battery.pdi_reports),
            joinedload(Battery.bms_record),
            joinedload(Battery.dispatch_record),
            joinedload(Battery.pack_test)
        )

        if battery_id:
            query = query.filter(Battery.battery_id.ilike(f"%{battery_id}%"))
        if date_from:
            query = query.filter(func.date(Battery.created_at) >= date_from)
        if date_to:
            query = query.filter(func.date(Battery.created_at) <= date_to)
        if status:
            if status == "failed":
                query = query.filter(Battery.had_ng_status == True)
            else:
                query = query.filter(Battery.overall_status == status.upper())

        total_items = query.count()
        total_pages = (total_items + page_size - 1) // page_size
        offset      = (page - 1) * page_size

        batteries = query.order_by(desc(Battery.created_at)).offset(offset).limit(page_size).all()

        results = []
        for b in batteries:
            pdi      = b.pdi_reports[0] if b.pdi_reports else None
            bms      = b.bms_record
            dispatch = b.dispatch_record
            pack     = b.pack_test

            results.append({
                "battery_id":           b.battery_id,
                "model":                b.model_id,
                "bms_id":               bms.bms_id          if bms      else "Not Assigned",
                "pack_test_result":     pack.final_result    if pack     else "PENDING",
                "pdi_result":           pdi.test_result      if pdi      else "PENDING",
                "status":               b.overall_status,
                "created_at":           b.created_at.strftime("%Y-%m-%d %H:%M") if b.created_at else "N/A",
                "assembled_at":         b.created_at.strftime("%d-%b-%Y")        if b.created_at else "N/A",
                "dispatch_destination": dispatch.customer_name if dispatch else None,
            })

        return {
            "success": True,
            "data": {
                "items":        results,
                "total_items":  total_items,
                "total_pages":  total_pages,
                "current_page": page
            }
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Traceability failed: {str(e)}")


@router.get("/cells/brands")
async def get_unique_brands(db: Session = Depends(get_db)):
    brands = db.query(CellGrading.brand).distinct().all()
    return {"success": True, "data": [b[0] for b in brands if b[0]]}