from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
from app.core.database import supabase

security = HTTPBearer()

def get_current_user(token=Depends(security)):
    try:
        # ✅ VALIDAZIONE UFFICIALE SUPABASE
        res = supabase.auth.get_user(token.credentials)

        if not res or not res.user:
            raise HTTPException(status_code=401, detail="Invalid token")

        return res.user.id

    except Exception as e:
        print("AUTH ERROR:", e)
        raise HTTPException(status_code=401, detail="Invalid token")
