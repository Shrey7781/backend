import asyncio
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, literal_column, desc

import traceback
from typing import List

from sqlalchemy import or_
from datetime import datetime, date
from typing import Optional
from app.database import get_db

from app.database import get_db, SessionLocal # Import SessionLocal for WS
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

# --- WebSocket Connection Manager ---
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

# --- Reusable Dashboard Logic ---
async def fetch_dashboard_stats(db: Session):
    
    today = datetime.now().date()
    
    total_cells = db.query(func.count(Cell.cell_id)).scalar() or 0
    batteries_count = db.query(func.count(Battery.battery_id)).scalar() or 0
    
    pdi_total = db.query(func.count(PDIReport.id)).scalar() or 0
    pdi_passed = db.query(func.count(PDIReport.id)).filter(PDIReport.test_result == 'Finished PASS').scalar() or 0
    pass_rate = f"{(pdi_passed / pdi_total * 100):.1f}%" if pdi_total > 0 else "0%"

    dispatched_today = db.query(func.count(Dispatch.id)).filter(func.date(Dispatch.dispatch_timestamp) == today).scalar() or 0
    failed_packs = db.query(func.count(Battery.battery_id)).filter(Battery.had_ng_status == True).scalar() or 0
    pending_pdi = db.query(func.count(Battery.battery_id)).outerjoin(PDIReport).filter(PDIReport.id == None).scalar() or 0

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
            "total_cells": {"value": str(total_cells), "change": "Total Inventory"},
            "batteries_assembled": {"value": str(batteries_count), "change": "Units"},
            "pdi_pass_rate": {"value": pass_rate, "change": "Quality Score"},
            "dispatched_today": {"value": str(dispatched_today), "change": "Today"},
            "failed_batteries": {"value": str(failed_packs), "change": "Requires Check"},
            "pending_inspection": {"value": str(pending_pdi), "change": "Queue"}
        },
        "recent_activity": [
            {
                "time": a.time.strftime("%H:%M") if a.time else "Now",
                "action": a.action,
                "id": a.id,
                "status": "SUCCESS" if a.status == "Finished PASS" else "ERROR"
            } for a in recent_pdi
        ],
        "stage_breakdown": [
            {"stage": "Cell Registration", "count": total_cells, "status": "ACTIVE"},
            {"stage": "Assembly", "count": batteries_count, "status": "ACTIVE"},
            {"stage": "Dispatch Today", "count": dispatched_today, "status": "COMPLETED"}
        ],
        "today_output": [
            {
                "battery_id": b.battery_id,
                "model": b.model,
                "stage": b.stage,
                "status": b.status,
                "updated_at": b.updated_at.strftime("%H:%M") if b.updated_at else "Today"
            } for b in today_output_query
        ]
    }

# --- Endpoints ---

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
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1),
    cell_id: Optional[str] = None,
    status: Optional[str] = None,
    model: Optional[str] = None, # This will now filter by 'brand' in grading
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db)
):
    try:
        # We use an outer join so we still see cells that haven't been graded yet
        query = db.query(Cell).outerjoin(CellGrading)

        if cell_id:
            query = query.filter(Cell.cell_id.ilike(f"%{cell_id}%"))
        
        # If 'model' is provided, we filter by the 'brand' column in CellGrading
        if model:
            query = query.filter(CellGrading.brand.ilike(f"%{model}%"))
            
        if status:
            if status == "REGISTERED":
                query = query.filter(CellGrading.id == None)
            elif status == "GRADED":
                query = query.filter(CellGrading.final_result == 'PASS')
            elif status == "ASSIGNED":
                query = query.filter(Cell.is_used == True)
            elif status == "FAILED":
                query = query.filter(CellGrading.final_result == 'FAIL')

        # FIX: Changed created_at to registration_date (from your model)
        if date_from:
            query = query.filter(func.date(Cell.registration_date) >= date_from)
        
        if date_to:
            query = query.filter(func.date(Cell.registration_date) <= date_to)

        total_items = query.count()
        total_pages = (total_items + page_size - 1) // page_size
        offset = (page - 1) * page_size
        
        # FIX: Sort by registration_date
        items = query.order_by(Cell.registration_date.desc()).offset(offset).limit(page_size).all()

        formatted_items = []
        for item in items:
            # Check the first grading record (if it exists)
            grading = item.gradings[0] if item.gradings else None
            
            current_status = "REGISTERED"
            if item.is_used:
                current_status = "ASSIGNED"
            elif grading:
                current_status = "GRADED" if grading.final_result == "PASS" else "FAILED"

            formatted_items.append({
                "cell_id": item.cell_id,
                "model": grading.brand if grading else "N/A", # Using Brand as Model
                "status": current_status,
                "registered_at": item.registration_date.isoformat() if item.registration_date else None,
                "voltage": item.sorting_voltage,
                "ir": item.ir_value_m_ohm
            })

        return {
            "success": True,
            "data": {
                "items": formatted_items,
                "total_items": total_items,
                "total_pages": total_pages,
                "current_page": page
            }
        }

    except Exception as e:
        import traceback
        traceback.print_exc() 
        print(f"Inventory Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
@router.get("/traceability")
async def get_battery_traceability(
    page: int = Query(1, ge=1),
    page_size: int = Query(15, ge=1),
    battery_id: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db)
):
    try:
        # Join Battery with its Model template
        query = db.query(Battery)

        if battery_id:
            query = query.filter(Battery.battery_id.ilike(f"%{battery_id}%"))
        
        # Date Filtering (Confirmed: created_at exists in your model)
        if date_from:
            query = query.filter(func.date(Battery.created_at) >= date_from)
        if date_to:
            query = query.filter(func.date(Battery.created_at) <= date_to)

        # Status Filtering logic
        if status:
            if status == "dispatched":
                query = query.join(Dispatch)
            elif status == "pdi":
                query = query.join(PDIReport)
            elif status == "failed":
                query = query.filter(Battery.had_ng_status == True)

        total_items = query.count()
        total_pages = (total_items + page_size - 1) // page_size
        offset = (page - 1) * page_size
        
        batteries = query.order_by(desc(Battery.created_at)).offset(offset).limit(page_size).all()

        results = []
        for b in batteries:
            # 1. Fetch linked records
            bms_record = db.query(BMS).filter(BMS.battery_id == b.battery_id).first()
            pack_test = db.query(PackTest).filter(PackTest.battery_id == b.battery_id).first()
            pdi = db.query(PDIReport).filter(PDIReport.battery_id == b.battery_id).first()
            dispatch = db.query(Dispatch).filter(Dispatch.battery_id == b.battery_id).first()
    
        

            # 3. Determine display status
            current_status = "REGISTERED"
            if dispatch: current_status = "DISPATCHED"
            elif pdi: current_status = "PDI_DONE"
            elif pack_test: current_status = "TESTED"

            results.append({
                "battery_id": b.battery_id,
                "model": b.model_id,
                # FIX: Use bms_id from your BMS model
                "bms_id": bms_record.bms_id if bms_record else "Not Assigned",
                # FIX: Use final_result from PackTest model
                "grading_result": pack_test.final_result if pack_test else "PENDING",
                "pdi_result": pdi.test_result if pdi else "PENDING",
                "status": current_status,
                "created_at": b.created_at.strftime("%Y-%m-%d %H:%M") if b.created_at else "N/A",
                "assembled_at": b.created_at.strftime("%d-%b-%Y") if b.created_at else "N/A",
                "dispatch_destination": dispatch.customer_name if dispatch else None,
                
            })

        return {
            "success": True,
            "data": {
                "items": results,
                "total_items": total_items,
                "total_pages": total_pages,
                "current_page": page
            }
        }

    except Exception as e:
        import traceback
        traceback.print_exc() 
        print(f"Traceability Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Traceability failed: {str(e)}")