from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.database import supabase
from app.core.security import get_current_user

router = APIRouter(prefix="/ratings", tags=["Ratings"])

class RatingReq(BaseModel):
    event_id: str
    rating: int

@router.post("")
def rate_event(payload: RatingReq, user_id: str = Depends(get_current_user)):
    supabase.table("event_ratings").upsert({
        "user_id": user_id,
        "event_id": payload.event_id,
        "rating": payload.rating,
    }, on_conflict="user_id,event_id").execute()

    return {"ok": True}

@router.get("/my")
def my_rating(event_id: str, user_id: str = Depends(get_current_user)):
    res = supabase.table("event_ratings") \
        .select("rating") \
        .eq("user_id", user_id) \
        .eq("event_id", event_id) \
        .limit(1) \
        .execute()

    return {
        "rating": res.data[0]["rating"] if res.data else None
    }

