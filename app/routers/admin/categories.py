from fastapi import APIRouter, HTTPException
from app.core.database import supabase
from typing import Optional

router = APIRouter(prefix="/admin/categories", tags=["admin-categories"])


# =====================================================
# LIST
# =====================================================

@router.get("")
def list_categories():
    return supabase.table("categories") \
        .select("id, name, slug, type, created_at") \
        .order("created_at", desc=True) \
        .execute().data


# =====================================================
# CREATE
# =====================================================

@router.post("")
def create_category(
    name: str,
    slug: str,
    type: str,
):
    res = supabase.table("categories").insert({
        "name": name,
        "slug": slug,
        "type": type,
    }).execute()

    if not res.data:
        raise HTTPException(400, "Failed to create category")

    return res.data[0]


# =====================================================
# UPDATE
# =====================================================

@router.put("/{category_id}")
def update_category(
    category_id: str,
    name: Optional[str] = None,
    slug: Optional[str] = None,
    type: Optional[str] = None,
):
    updates = {}

    if name is not None:
        updates["name"] = name
    if slug is not None:
        updates["slug"] = slug
    if type is not None:
        updates["type"] = type

    if not updates:
        raise HTTPException(400, "No fields to update")

    res = supabase.table("categories") \
        .update(updates) \
        .eq("id", category_id) \
        .execute()

    if not res.data:
        raise HTTPException(404, "Category not found")

    return res.data[0]


# =====================================================
# DELETE
# =====================================================

@router.delete("/{category_id}")
def delete_category(category_id: str):
    supabase.table("categories") \
        .delete() \
        .eq("id", category_id) \
        .execute()

    return {"status": "deleted"}
