import os
from datetime import datetime, timedelta
from typing import List, Optional, Any, Dict
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Airport, Flight, Passenger, Booking

app = FastAPI(title="Flight Booking API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def to_str_id(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    doc = dict(doc)
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


# --------- Models for requests/responses ---------
class SearchQuery(BaseModel):
    origin: str = Field(..., min_length=3, max_length=3)
    destination: str = Field(..., min_length=3, max_length=3)
    date: datetime = Field(..., description="Date (00:00 UTC) to search on")


class PassengerIn(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    document_number: Optional[str] = None


class BookingRequest(BaseModel):
    flight_id: str
    contact_email: EmailStr
    passengers: List[PassengerIn]


class BookingResponse(BaseModel):
    booking_id: str
    status: str


# --------- Utility and seed data ---------
AIRPORTS_SAMPLE = [
    {"code": "IKA", "name": "Imam Khomeini International", "city": "Tehran", "country": "Iran"},
    {"code": "MHD", "name": "Mashhad International", "city": "Mashhad", "country": "Iran"},
    {"code": "SYZ", "name": "Shiraz International", "city": "Shiraz", "country": "Iran"},
    {"code": "IFN", "name": "Isfahan International", "city": "Isfahan", "country": "Iran"},
    {"code": "THR", "name": "Mehrabad", "city": "Tehran", "country": "Iran"},
]

AIRLINES = ["IR", "W5", "QB", "EP"]


def ensure_seed():
    if db is None:
        return
    # Seed airports
    if db["airport"].count_documents({}) == 0:
        db["airport"].insert_many(AIRPORTS_SAMPLE)
    # Seed flights for next 5 days between sample routes, if empty
    if db["flight"].count_documents({}) == 0:
        flights = []
        base = datetime.utcnow().replace(hour=6, minute=0, second=0, microsecond=0)
        routes = [("IKA", "MHD"), ("IKA", "SYZ"), ("THR", "MHD"), ("IFN", "IKA")]
        price_base = {("IKA", "MHD"): 70, ("IKA", "SYZ"): 65, ("THR", "MHD"): 60, ("IFN", "IKA"): 55}
        for d in range(0, 5):
            for (o, dst) in routes:
                dep = base + timedelta(days=d, hours=(d % 3) * 3)
                arr = dep + timedelta(hours=1, minutes=10)
                airline = AIRLINES[(d + len(flights)) % len(AIRLINES)]
                flight_number = f"{airline}-{100 + d*5 + len(flights)%5}"
                price = float(price_base[(o, dst)] + (d * 5))
                f = Flight(
                    flight_number=flight_number,
                    origin=o,
                    destination=dst,
                    departure_time=dep,
                    arrival_time=arr,
                    price=price,
                    seats_total=120,
                    seats_available=120 - (d * 3),
                )
                flights.append(f.model_dump())
        if flights:
            db["flight"].insert_many(flights)


@app.on_event("startup")
def startup_event():
    try:
        ensure_seed()
    except Exception:
        pass


# --------- Basic endpoints ---------
@app.get("/")
def root():
    return {"message": "Flight Booking API ready"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Connected"
            response["connection_status"] = "Connected"
            response["collections"] = db.list_collection_names()
    except Exception as e:
        response["database"] = f"⚠️ {str(e)[:80]}"
    return response


# --------- Airports ---------
@app.get("/api/airports")
def list_airports():
    airports = get_documents("airport")
    return [to_str_id(a) for a in airports]


# --------- Flights ---------
@app.post("/api/flights/search")
def search_flights(q: SearchQuery):
    # Normalize date: search that calendar day UTC
    start = q.date.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    flts = db["flight"].find({
        "origin": q.origin.upper(),
        "destination": q.destination.upper(),
        "departure_time": {"$gte": start, "$lt": end},
        "seats_available": {"$gt": 0},
    }).sort("departure_time", 1)
    return [to_str_id(f) for f in flts]


@app.get("/api/flights/{flight_id}")
def get_flight(flight_id: str):
    try:
        oid = ObjectId(flight_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid flight id")
    f = db["flight"].find_one({"_id": oid})
    if not f:
        raise HTTPException(status_code=404, detail="Flight not found")
    return to_str_id(f)


# --------- Bookings ---------
@app.post("/api/bookings", response_model=BookingResponse)
def create_booking(req: BookingRequest):
    # Validate flight exists and has enough seats
    try:
        fid = ObjectId(req.flight_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid flight id")
    flight = db["flight"].find_one({"_id": fid})
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    if flight.get("seats_available", 0) < len(req.passengers):
        raise HTTPException(status_code=400, detail="Not enough seats available")

    # Build booking document
    passengers = [
        Passenger(
            first_name=p.first_name,
            last_name=p.last_name,
            email=p.email,
            document_number=p.document_number,
        ).model_dump()
        for p in req.passengers
    ]
    total_amount = float(flight.get("price", 0.0)) * len(passengers)
    booking = Booking(
        flight_id=req.flight_id,
        contact_email=req.contact_email,
        passengers=passengers,  # type: ignore
        total_amount=total_amount,
        status="confirmed",
    )
    bid = create_document("booking", booking)

    # Decrease seats
    db["flight"].update_one({"_id": fid}, {"$inc": {"seats_available": -len(passengers)}})

    return BookingResponse(booking_id=bid, status="confirmed")


@app.get("/api/bookings")
def list_bookings(email: Optional[EmailStr] = Query(None)):
    flt: dict = {}
    if email:
        flt["contact_email"] = str(email)
    items = get_documents("booking", flt)
    # Join with flight basic info
    results = []
    for b in items:
        fb = db["flight"].find_one({"_id": ObjectId(b["flight_id"])}) if b.get("flight_id") else None
        b = to_str_id(b)
        if fb:
            b["flight"] = to_str_id(fb)
        results.append(b)
    return results


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
