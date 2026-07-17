from fastapi import APIRouter, Depends, HTTPException
from app.routes.auth import get_current_user  # adjust if needed

router = APIRouter(prefix="/lss", tags=["lss"])

@router.get("/project")
def get_lss_projects(user=Depends(get_current_user)):
    if user.plan != "business":
        raise HTTPException(status_code=403, detail="Access denied")
    return {"message": "Your LSS Projects"}

@router.post("/sipoc")
def create_sipoc(user=Depends(get_current_user)):
    if user.plan != "business":
        raise HTTPException(status_code=403, detail="Access denied")
    return {"message": "SIPOC created (stub)"}
