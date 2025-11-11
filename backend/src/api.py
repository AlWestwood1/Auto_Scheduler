import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import RequestHandler

app = FastAPI()

origins = [
    "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class EventJson(BaseModel):
    summary: str
    start_time: str
    end_time: str
    earliest_start: str = None
    latest_end: str = None
    is_flexible: bool
    duration_minutes: int = None
    google_id: str = None

class EventList(BaseModel):
    events: list[EventJson]


# API Endpoints
@app.get("/events", response_model=EventList)
def get_events(in_range: bool = False, from_date: str = "", to_date: str = ""):
    rh = RequestHandler()
    events = rh.get_events(in_range, from_date, to_date)
    print(events)
    return EventList(events=events)

@app.post("/events")
def add_event(event: EventJson):
    rh = RequestHandler()
    rh.add_event(event.model_dump())
    return {"message": f"Event {event.summary} added successfully"}

@app.put("/events/{google_id}")
def edit_event(google_id: str, updated_event: EventJson):
    print('editing event')
    rh = RequestHandler()
    rh.edit_event(google_id, updated_event.model_dump())
    return {"message": f"Event {google_id} edited successfully"}


@app.delete("/events/{google_id}")
def delete_event(google_id: str):
    rh = RequestHandler()
    rh.del_event(google_id)
    return {"message": f"Event {google_id} deleted successfully"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)