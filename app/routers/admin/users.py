from fastapi import APIRouter, HTTPException
from app.core.database import supabase
from typing import Optional
import uuid
from datetime import datetime
from app.services.send_email_waitlist import send_waitlist_email
import os

router = APIRouter(prefix="/admin", tags=["admin"])

FRONTEND_URL = os.getenv("FRONTEND_URL")

if not FRONTEND_URL:
    raise RuntimeError("FRONTEND_URL env variable not set")
    
def generate_invite_token() -> str:
    return str(uuid.uuid4())

# =====================================================
# USERS
# =====================================================

@router.get("/users")
def list_users():
    """
    Lista utenti (profiles)
    """
    return supabase.table("profiles") \
        .select("""
            id,
            username,
            nickname,
            avatar_url,
            bio,
            city_id,
            created_at
        """) \
        .order("created_at", desc=True) \
        .execute().data


@router.get("/users/{user_id}")
def get_user(user_id: str):
    """
    Dettaglio utente (profile + email auth)
    """
    profile = supabase.table("profiles") \
        .select("*") \
        .eq("id", user_id) \
        .single() \
        .execute()

    if not profile.data:
        raise HTTPException(404, "User not found")

    try:
        auth_user = supabase.auth.admin.get_user_by_id(user_id)
        email = auth_user.user.email if auth_user.user else None
    except Exception:
        email = None

    return {
        **profile.data,
        "email": email,
    }


@router.put("/users/{user_id}")
def update_user(
    user_id: str,
    nickname: Optional[str] = None,
    username: Optional[str] = None,
    bio: Optional[str] = None,
    city_id: Optional[str] = None,
):
    """
    Aggiorna dati profilo utente
    """
    updates = {}

    if nickname is not None:
        updates["nickname"] = nickname
    if username is not None:
        updates["username"] = username
    if bio is not None:
        updates["bio"] = bio
    if city_id is not None:
        updates["city_id"] = city_id

    if not updates:
        raise HTTPException(400, "No fields to update")

    res = supabase.table("profiles") \
        .update(updates) \
        .eq("id", user_id) \
        .execute()

    if not res.data:
        raise HTTPException(404, "User not found")

    return res.data[0]


@router.put("/users/{user_id}/email")
def update_user_email(user_id: str, email: str):
    """
    Aggiorna email utente (auth.users)
    """
    try:
        supabase.auth.admin.update_user_by_id(
            user_id,
            {"email": email}
        )
    except Exception as e:
        raise HTTPException(400, str(e))

    return {"status": "email_updated"}


@router.delete("/users/{user_id}")
def delete_user(user_id: str):
    """
    Elimina utente (profile + auth)
    """
    supabase.table("profiles") \
        .delete() \
        .eq("id", user_id) \
        .execute()

    try:
        supabase.auth.admin.delete_user(user_id)
    except Exception:
        pass

    return {"status": "deleted"}


# =====================================================
# WAITLIST
# =====================================================

@router.get("/waitlist")
def list_waitlist():
    """
    Lista waitlist
    """
    return supabase.table("waitlist") \
        .select("*") \
        .order("created_at", desc=True) \
        .execute().data

@router.post("/waitlist/{id}/approve")
def approve_waitlist(id: str):
    token = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    res = supabase.table("waitlist") \
        .update({
            "status": "approved",
            "invite_token": token,
            "invited_at": now,
        }) \
        .eq("id", id) \
        .execute()

    if not res.data:
        raise HTTPException(404, "Waitlist entry not found")

    w = res.data[0]

    invite_link = f"{FRONTEND_URL}/auth/register?invite={token}"

    # ⛔️ QUI CI COLLEGHI UN PROVIDER EMAIL
    send_waitlist_email(
        to=w["email"],
        link=invite_link,
        name=w.get("full_name")
    )

    return {
        "status": "approved",
        "invite_link": invite_link
    }

@router.post("/waitlist/{id}/reject")
def reject_waitlist(id: str):
    """
    Rifiuta richiesta waitlist
    """
    res = supabase.table("waitlist") \
        .update({"status": "rejected"}) \
        .eq("id", id) \
        .execute()

    if not res.data:
        raise HTTPException(404, "Waitlist entry not found")

    return {"status": "rejected"}

@router.get("/auth/invite/{token}")
def verify_invite(token: str):
    res = supabase.table("waitlist") \
        .select("id,email,status") \
        .eq("invite_token", token) \
        .eq("status", "approved") \
        .single() \
        .execute()

    if not res.data:
        raise HTTPException(400, "Invalid invite")

    return {
        "email": res.data["email"]
    }

@router.delete("/waitlist/{id}")
def delete_waitlist(id: str):
    """
    Elimina entry waitlist
    """
    supabase.table("waitlist") \
        .delete() \
        .eq("id", id) \
        .execute()

    return {"status": "deleted"}

@router.post("/waitlist/consume")
def consume_invite(token: str):
    res = supabase.table("waitlist") \
        .update({"invite_token": None}) \
        .eq("invite_token", token) \
        .execute()

    if not res.data:
        raise HTTPException(400, "Invalid invite")

    return {"status": "consumed"}

