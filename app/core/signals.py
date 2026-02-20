from app.routers.admin_router import manager, fetch_dashboard_stats
from app.database import SessionLocal

async def trigger_dashboard_update():
    """Call this anywhere to refresh the admin dashboard live"""
    with SessionLocal() as db:
        new_stats = await fetch_dashboard_stats(db)
        await manager.broadcast({"success": True, "data": new_stats})