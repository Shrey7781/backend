from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware # Missing import
from app.database import engine, Base


from app.models.cell import Cell, CellGrading
from app.models.battery import  BatteryModel
from app.models.welding import LaserWelding, SpotWelding
# from app.models.battery import BatteryPack, PackTestResult
# from app.models.grading import GradingStepResult


from app.routers import cell_router, battery_router, battery_pack_router, bms_router, welding_router, pdi_router


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Maxvolt Energies Production Portal")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For production, change this to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],  # This enables OPTIONS, POST, GET, etc.
    allow_headers=["*"],
)


app.include_router(cell_router.router)
app.include_router(battery_pack_router.router)
app.include_router(battery_router.router)
app.include_router(bms_router.router)
app.include_router(welding_router.router)
app.include_router(pdi_router.router)

@app.get("/")
def home():
    return {"message": "Backend is Live"}