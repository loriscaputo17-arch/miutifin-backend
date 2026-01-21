from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.database import supabase
from app.core.security import get_current_user

router = APIRouter(prefix="/going", tags=["Going"])

class GoingReq(BaseModel):
    event_id: str

@router.post("")
def going_add(payload: GoingReq, user_id: str = Depends(get_current_user)):
    res = supabase.table("event_attendees").insert({
        "user_id": user_id,
        "event_id": event_id,
    }).execute()

    if not res.data:
        raise HTTPException(status_code=400, detail="Unable to save attendance")
    
    return {"going": True}

@router.delete("")
def going_remove(payload: GoingReq, user=Depends(get_current_user)):
    supabase.table("event_attendees") \
        .delete() \
        .eq("user_id", user["id"]) \
        .eq("event_id", payload.event_id) \
        .execute()

    return {"going": False}

@router.get("/check")
def going_check(event_id: str, user_id: str = Depends(get_current_user)):
    res = supabase.table("event_attendees") \
        .select("id") \
        .eq("user_id", user_id) \
        .eq("event_id", event_id) \
        .limit(1) \
        .execute() 

    return {"going": bool(res.data)}

@router.get("/count")
def going_count(event_id: str):
    res = supabase.table("event_attendees") \
        .select("id", count="exact") \
        .eq("event_id", event_id) \
        .execute()

    return {"count": res.count}
