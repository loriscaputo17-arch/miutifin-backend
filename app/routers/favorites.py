from fastapi import APIRouter, Depends, Query
from app.core.database import supabase
from app.core.security import get_current_user

router = APIRouter(prefix="/favorites", tags=["favorites"])


@router.post("")
def add_favorite(
    payload: dict,
    user_id: str = Depends(get_current_user),
):
    supabase.table("user_favorites").insert({
        "user_id": user_id,
        "entity_type": payload["entity_type"],
        "entity_id": payload["entity_id"],
    }).execute()

    return {"ok": True}

@router.get("/check")
def check_favorite(
    entity_type: str = Query(...),
    entity_id: str = Query(...),
    user_id: str = Depends(get_current_user),
):
    res = (
        supabase.table("user_favorites")
        .select("id")
        .eq("user_id", user_id)
        .eq("entity_type", entity_type)
        .eq("entity_id", entity_id)
        .limit(1)
        .execute()
    )

    return {"liked": len(res.data) > 0}

@router.delete("")
def remove_favorite(
    payload: dict,
    user_id: str = Depends(get_current_user),
): 
    supabase.table("user_favorites") \
        .delete() \
        .eq("user_id", user_id) \
        .eq("entity_type", payload["entity_type"]) \
        .eq("entity_id", payload["entity_id"]) \
        .execute()

    return {"ok": True}
