import asyncio
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from sqlalchemy import func, case, literal_column
from datetime import datetime
import traceback
from typing import List

from app.database import get_db, SessionLocal # Import SessionLocal for WS
from app.models.cell import Cell
from app.models.battery_pack import Battery
from app.models.pdi import PDIReport
from app.models.dispatch import Dispatch

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
    """Refactored logic to be used by both GET and WebSocket"""
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
async def websocket_dashboard(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Create a new DB session for each update cycle
            with SessionLocal() as db:
                data = await fetch_dashboard_stats(db)
                await websocket.send_json({"success": True, "data": data})
            
            # Update every 30 seconds, or wait for a broadcast trigger
            await asyncio.sleep(30) 
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WS Error: {e}")
        manager.disconnect(websocket)