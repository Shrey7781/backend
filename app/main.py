from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware 
from app.database import engine, Base
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session        
from sqlalchemy import text              
from app.database import engine, Base, get_db  


from app.routers import cell_router, battery_router, battery_pack_router, bms_router, welding_router, pdi_router, dispatch_router, report_router, user_router


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Maxvolt Energies Production Portal")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://maxtrace.maxvoltenergy.com"],  
    allow_credentials=True,
    allow_methods=["*"],  
    allow_headers=["*"],
)


app.include_router(cell_router.router)
app.include_router(battery_pack_router.router)
app.include_router(battery_router.router)
app.include_router(bms_router.router)
app.include_router(welding_router.router)
app.include_router(pdi_router.router)
app.include_router(dispatch_router.router)
app.include_router(user_router.router)
app.include_router(report_router.router)
from app.routers import admin_router
app.include_router(admin_router.router)

@app.get("/")
def home():
    return {"message": "Backend is Live"}

@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
      
        db.execute(text("SELECT 1"))
        return {
            "status":   "healthy",
            "database": "connected"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"status": "unhealthy", "database": str(e)}
        )