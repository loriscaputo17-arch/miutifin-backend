from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import (
    health,
    search,
    home,
    events,
    places,
    ingestions_dice,
    submissions,
    favorites,
    flyers,
    going,
    ratings,
    plans
)
from app.routers.admin import submissions as admin_submissions
from app.routers.admin import events as admin_events

app = FastAPI(
    title="Miutifin API",
    version="0.1.0",
)

# -----------------------
# CORS
# -----------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------
# Routers
# -----------------------

app.include_router(health.router)
app.include_router(search.router)
app.include_router(home.router)
app.include_router(events.router)
app.include_router(places.router)
app.include_router(ingestions_dice.router)
app.include_router(submissions.router)
app.include_router(favorites.router)
app.include_router(flyers.router)
app.include_router(going.router)
app.include_router(ratings.router)
app.include_router(plans.router)

app.include_router(admin_submissions.router)
app.include_router(admin_events.router)
# -----------------------
# Root (opzionale, utile)
# -----------------------

@app.get("/")
def root():
    return {
        "name": "Miutifin API",
        "version": "0.1.0",
        "status": "ok"
    }
