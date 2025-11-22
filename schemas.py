"""
Database Schemas for Flight Booking App

Each Pydantic model represents a MongoDB collection. The collection name is the
lowercase of the class name (e.g., Flight -> "flight").
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime


class Airport(BaseModel):
    code: str = Field(..., description="IATA code, e.g., LAX, IKA", min_length=3, max_length=3)
    name: str = Field(..., description="Airport name")
    city: str = Field(..., description="City name")
    country: str = Field(..., description="Country name")


class Flight(BaseModel):
    flight_number: str = Field(..., description="Airline flight number, e.g., W5-1112")
    origin: str = Field(..., description="Origin IATA code")
    destination: str = Field(..., description="Destination IATA code")
    departure_time: datetime = Field(..., description="Departure time (ISO)")
    arrival_time: datetime = Field(..., description="Arrival time (ISO)")
    price: float = Field(..., ge=0, description="Price in USD")
    seats_total: int = Field(..., ge=1, description="Total seat capacity")
    seats_available: int = Field(..., ge=0, description="Available seats")


class Passenger(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    document_number: Optional[str] = None


class Booking(BaseModel):
    flight_id: str = Field(..., description="Flight ObjectId as string")
    contact_email: EmailStr
    passengers: List[Passenger]
    total_amount: float = Field(..., ge=0)
    status: str = Field("reserved", description="reserved | confirmed | cancelled")
