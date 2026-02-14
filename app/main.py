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
    plans,
    explore,
    neighborhoods,
    ingestions_xceed,
    ingestions_eventbrite,
    ingestions_partiful,
    ingestions_resident_advisor
)
from app.routers.admin import submissions as admin_submissions
from app.routers.admin import events as admin_events
from app.routers.admin import places as admin_places
from app.routers.admin import stats as admin_stats

from app.routers.admin import users as admin_users
from app.routers.admin import categories as admin_categories
from app.routers.admin import ingestions as admin_ingestions

from app.routers.ingestions.places import osm as ingestion_places_osm
from app.routers import map as map_router

app = FastAPI(
    title="Miutifin API",
    version="0.1.0",
)

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

app.include_router(health.router)
app.include_router(search.router)
app.include_router(home.router)
app.include_router(events.router)
app.include_router(places.router)
app.include_router(ingestions_dice.router)
app.include_router(ingestions_xceed.router)
app.include_router(ingestions_eventbrite.router)
app.include_router(ingestions_partiful.router)
app.include_router(ingestions_resident_advisor.router)
app.include_router(submissions.router)
app.include_router(favorites.router)
app.include_router(flyers.router)
app.include_router(going.router)
app.include_router(ratings.router)
app.include_router(plans.router)
app.include_router(neighborhoods.router)
app.include_router(explore.router)

app.include_router(admin_submissions.router)
app.include_router(admin_events.router)
app.include_router(admin_places.router)
app.include_router(admin_stats.router)
app.include_router(admin_users.router)
app.include_router(admin_categories.router)
app.include_router(admin_ingestions.router)

app.include_router(ingestion_places_osm.router)
app.include_router(map_router.router)

@app.get("/")
def root():
    return {
        "name": "Miutifin API",
        "version": "0.1.0",
        "status": "ok"
    }
