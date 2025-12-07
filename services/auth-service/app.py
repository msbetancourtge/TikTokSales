from datetime import datetime, timedelta
import os
import logging
import uuid

from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel, EmailStr
from passlib.hash import bcrypt
import jwt

from db import get_supabase_client

logger = logging.getLogger("auth-service")
app = FastAPI(title="TikTokSales Auth Service")

JWT_SECRET = os.getenv("JWT_SECRET") or os.getenv("SUPABASE_SERVICE_KEY")
JWT_ALGORITHM = "HS256"


class ClientRegister(BaseModel):
    email: EmailStr
    name: str
    password: str
    phone: str | None = None


class StreamerRegister(BaseModel):
    username: str
    platform: str | None = "tiktok"
    follower_count: int | None = 0


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class PurchaseRequest(BaseModel):
    product_id: int
    streamer: str
    quantity: int = 1
    total_price: float | None = None
    payment_method: str | None = None


def create_token(payload: dict, expires_days: int = 7) -> str:
    to_encode = payload.copy()
    to_encode.update({"exp": datetime.utcnow() + timedelta(days=expires_days)})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return data
    except Exception as e:
        logger.debug("Token decode failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token")


def get_current_client(authorization: str | None = Header(None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")
    token = parts[1]
    return decode_token(token)


@app.post("/clients/register")
def register_client(payload: ClientRegister):
    supabase = get_supabase_client()
    # check existing
    resp = supabase.table("clients").select("id,email").eq("email", payload.email).execute()
    if resp.data and len(resp.data) > 0:
        raise HTTPException(status_code=400, detail="Client already exists")

    pw_hash = bcrypt.hash(payload.password)
    record = {
        "email": payload.email,
        "name": payload.name,
        "password_hash": pw_hash,
        "phone": payload.phone,
        "created_at": datetime.utcnow().isoformat(),
    }
    insert = supabase.table("clients").insert(record).execute()
    if insert.error:
        raise HTTPException(status_code=500, detail=str(insert.error))
    created = insert.data[0]
    # return token
    token = create_token({"client_id": created.get("id"), "email": created.get("email")})
    return {"client": {"id": created.get("id"), "email": created.get("email"), "name": created.get("name")}, "token": token}


@app.post("/streamers/register")
def register_streamer(payload: StreamerRegister):
    supabase = get_supabase_client()
    resp = supabase.table("streamers").select("id,username").eq("username", payload.username).execute()
    if resp.data and len(resp.data) > 0:
        raise HTTPException(status_code=400, detail="Streamer already exists")
    record = {
        "username": payload.username,
        "platform": payload.platform,
        "follower_count": payload.follower_count or 0,
        "created_at": datetime.utcnow().isoformat(),
    }
    insert = supabase.table("streamers").insert(record).execute()
    if insert.status_code != 201:
        raise HTTPException(status_code=500, detail=f"Supabase insert failed: {insert.data}")
    return {"streamer": insert.data[0]}


@app.post("/login")
def login(payload: LoginRequest):
    supabase = get_supabase_client()
    resp = supabase.table("clients").select("id,email,password_hash,name").eq("email", payload.email).execute()
    if not resp.data or len(resp.data) == 0:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    client = resp.data[0]
    if not bcrypt.verify(payload.password, client.get("password_hash")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token({"client_id": client.get("id"), "email": client.get("email")})
    return {"token": token, "client": {"id": client.get("id"), "email": client.get("email"), "name": client.get("name")}}


@app.post("/purchase")
def create_purchase(payload: PurchaseRequest, current=Depends(get_current_client)):
    supabase = get_supabase_client()
    client_id = current.get("client_id")
    # create order_number
    order_number = f"ORD-{uuid.uuid4().hex[:10]}"
    record = {
        "order_number": order_number,
        "product_id": payload.product_id,
        "buyer": current.get("email"),
        "streamer": payload.streamer,
        "quantity": payload.quantity,
        "total_price": payload.total_price,
        "payment_method": payload.payment_method,
        "created_at": datetime.utcnow().isoformat(),
    }
    insert = supabase.table("orders").insert(record).execute()
    if insert.error:
        raise HTTPException(status_code=500, detail=str(insert.error))
    order = insert.data[0]
    # Optionally link buyer_id if column exists
    try:
        # attempt to update buyer_id using client_id (if column exists)
        if client_id:
            supabase.table("orders").update({"buyer_id": client_id}).eq("id", order.get("id")).execute()
    except Exception:
        pass
    return {"order": order}


@app.get("/health")
def health():
    return {"status": "ok", "service": "auth-service"}
