from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class User:
    user_id: int
    username: Optional[str]
    first_name: str
    role: int
    venue_id: Optional[int] = None
    table_number: Optional[int] = None
    created_at: Optional[datetime] = None
    is_blocked: bool = False
    language: str = 'ru'

@dataclass
class Venue:
    venue_id: int
    name: str
    city: str
    owner_phone: str
    owner_email: str
    created_at: datetime
    is_active: bool = True
    table_count: int = 12
    songs_per_table: int = 2
    table_mode: str = "sequential"
    chat_enabled: bool = False
    chat_link: Optional[str] = None
    vip_description: Optional[str] = None
    vip_description_ro: Optional[str] = None
    vip_cashback: float = 0

@dataclass
class Service:
    service_id: int
    venue_id: int
    name: str
    description: str
    price: float
    is_free: bool = False

@dataclass
class Order:
    order_id: int
    venue_id: int
    table_number: int
    user_id: int
    service_id: int
    song_name: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    position: int = 0
    is_next: int = 0
    marked_next_at: Optional[datetime] = None
    started_at: Optional[datetime] = None

@dataclass
class VIPClient:
    user_id: int
    venue_id: int
    balance: float
    cashback_percent: float
    added_at: datetime

@dataclass
class Song:
    song_id: int
    venue_id: int
    artist: str
    title: str
    code: Optional[str] = None
