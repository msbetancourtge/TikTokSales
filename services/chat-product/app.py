"""
Chat-Product Service: Handles chat interactions with product recommendations using NLP service integration.
"""
import os
import logging
from typing import Optional
import asyncio
import json
from datetime import datetime
import redis.asyncio as aioredis
import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator

from db import initialize_supabase, get_supabase_client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Chat-Product Service",
    description="Chat service with NLP-powered product recommendations",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment variables
NLP_SERVICE_URL = os.getenv("NLP_SERVICE_URL", "http://nlp-service:8001")
VISION_SERVICE_URL = os.getenv("VISION_SERVICE_URL", "http://vision-service:8002")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "http://72.61.76.44:5678/webhook-test/37b254d7-d925-4e3a-a725-edbbe4f225b8")
redis_client: aioredis.Redis | None = None

# Initialize Supabase on startup
db_initialized = False


@app.on_event("startup")
async def startup_event():
    global db_initialized, redis_client
    db_initialized = initialize_supabase()
    # Redis init
    try:
        redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
        await redis_client.ping()
        logger.info("Connected to Redis at %s", REDIS_URL)
    except Exception as e:
        logger.error("Failed to connect to Redis: %s", e)
        redis_client = None
    if db_initialized:
        logger.info("Chat-Product service started with Supabase connected")
    else:
        logger.info("Chat-Product service started (Supabase offline)")



class ChatMessage(BaseModel):
    """Chat message payload from live stream comments.
    
    Note: user_id is the commenter's username/handle from the platform (TikTok, etc).
    Users do NOT need to be registered in our system to submit comments.
    """
    user_id: str = Field(..., min_length=1, max_length=255, description="Commenter username from platform (no registration required)")
    streamer_id: str = Field(..., min_length=1, max_length=255, description="Streamer username")
    message: str = Field(..., min_length=1, max_length=2000, description="Comment/chat message content")
    
    @validator('message')
    def message_must_not_be_empty(cls, v):
        if not v or v.isspace():
            raise ValueError('message cannot be empty or whitespace only')
        return v.strip()


class IncomingComment(BaseModel):
    """Incoming comment from TikTok/stream sources."""
    streamer: str = Field(..., min_length=1, max_length=255)
    client: str = Field(..., min_length=1, max_length=255)
    timestamp: Optional[str] = None  # ISO string preferible
    message: str = Field(..., min_length=1, max_length=2000)

    @validator("timestamp", always=True)
    def ensure_timestamp(cls, v):
        if not v:
            return datetime.utcnow().isoformat()
        return v
    
    @validator("message")
    def message_not_empty(cls, v):
        if not v or v.isspace():
            raise ValueError("message cannot be empty or whitespace only")
        return v.strip()


class ChatResponse(BaseModel):
    """Chat response with NLP intent, product recommendations, and purchase info."""
    user_id: str
    streamer_id: str
    message: str
    intent: str  # "yes" or "no" - buying intent from webhook
    cantidad: int
    timestamp: str
    matched_product: Optional[dict] = None  # Product matched by vision service
    recommended_products: list = []
    response_text: str
    payment_ready: bool = False  # True if product matched and ready for payment


class CommentQueueResponse(BaseModel):
    """Response after queuing a comment."""
    ok: bool
    queued_to: str
    stream: str = "comments_stream"
    timestamp: str


class ProcessQueueRequest(BaseModel):
    """Request to process a user's message queue."""
    streamer_id: str = Field(..., min_length=1, max_length=255, description="Streamer username")
    user_id: str = Field(..., min_length=1, max_length=255, description="User/client username from platform")


class ProcessQueueResponse(BaseModel):
    """Response after processing a user's message queue."""
    user_id: str
    streamer_id: str
    messages_processed: int
    intent: str  # "yes" or "no"
    cantidad: int
    matched_product: Optional[dict] = None
    payment_ready: bool = False
    response_text: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    service: str = "chat-product"


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(status="healthy", service="chat-product")


@app.post("/chat", response_model=ChatResponse)
async def process_chat(payload: ChatMessage):
    """
    Process a chat message and return NLP intent + product recommendations.
    
    Args:
        payload: Chat message from user
    
    Returns:
        ChatResponse with intent prediction and recommendations
    """
    try:
        # Call n8n webhook to classify intent
        user_message = payload.message
        intent = "no"  # Default: no buying intent
        cantidad = 0
        timestamp = datetime.utcnow().isoformat()
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                webhook_response = await client.post(
                    N8N_WEBHOOK_URL,
                    json={"message": user_message},
                    headers={"Content-Type": "application/json"}
                )
                if webhook_response.status_code == 200:
                    result = webhook_response.json()
                    logger.info(f"Raw webhook response: {result}")
                    
                    # Parse webhook response: [{"intent": "yes"}] or [{"intent": "no"}]
                    try:
                        if isinstance(result, list) and len(result) > 0:
                            first_item = result[0]
                            intent = first_item.get("intent", "no").lower()
                            cantidad = int(first_item.get("cantidad", 0))
                        elif isinstance(result, dict):
                            intent = result.get("intent", "no").lower()
                            cantidad = int(result.get("cantidad", 0))
                        
                        logger.info(f"Intent classification from n8n: intent={intent}, cantidad={cantidad}")
                    except (KeyError, TypeError, AttributeError) as parse_err:
                        logger.warning(f"Failed to parse webhook response: {parse_err}")
                        intent = "no"
                        cantidad = 0
                else:
                    logger.warning(f"n8n webhook returned status {webhook_response.status_code}")
        except Exception as e:
            logger.error(f"Failed to call n8n webhook for intent classification: {e}")
            intent = "no"
            cantidad = 0
        
        # Initialize response variables
        matched_product = None
        payment_ready = False
        recommended_products = []
        response_text = "¿En qué puedo ayudarte?"
        
        # If buying intent detected, find product from live stream frame
        if intent == "yes":
            try:
                # Step 1: Find the closest frame from streamer_frames by timestamp
                frame_url = None
                if db_initialized:
                    supabase = get_supabase_client()
                    # Get frames for this streamer, ordered by timestamp (closest first)
                    frames_resp = supabase.table("streamer_frames") \
                        .select("id,minio_url,frame_timestamp") \
                        .eq("streamer", payload.streamer_id) \
                        .order("frame_timestamp", desc=True) \
                        .limit(1) \
                        .execute()
                    
                    if frames_resp.data and len(frames_resp.data) > 0:
                        frame_url = frames_resp.data[0].get("minio_url")
                        logger.info(f"Found frame for streamer {payload.streamer_id}: {frame_url}")
                    else:
                        logger.warning(f"No frames found for streamer {payload.streamer_id}")
                
                # Step 2: Call vision-service to match product from frame (MinIO URL)
                if frame_url:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        vision_response = await client.post(
                            f"{VISION_SERVICE_URL}/match_product",
                            json={
                                "frame_urls": [frame_url],
                                "streamer_id": payload.streamer_id
                            },
                            headers={"Content-Type": "application/json"}
                        )
                        if vision_response.status_code == 200:
                            vision_result = vision_response.json()
                            product_id = vision_result.get("productId")
                            logger.info(f"Vision service matched product_id: {product_id}")
                            
                            # Step 3: Get product details from database
                            if product_id and db_initialized:
                                product_resp = supabase.table("products") \
                                    .select("id,name,price,description,image_url,streamer_id") \
                                    .eq("id", product_id) \
                                    .limit(1) \
                                    .execute()
                                
                                if product_resp.data and len(product_resp.data) > 0:
                                    product = product_resp.data[0]
                                    matched_product = {
                                        "id": product.get("id"),
                                        "name": product.get("name"),
                                        "price": product.get("price"),
                                        "description": product.get("description"),
                                        "image_url": product.get("image_url"),
                                        "cantidad": cantidad,
                                        "total": float(product.get("price", 0)) * cantidad
                                    }
                                    payment_ready = True
                                    response_text = f"¡Encontré el producto! {product.get('name')} - ${product.get('price')}. ¿Deseas proceder con la compra de {cantidad} unidad(es)?"
                                    logger.info(f"Product matched and ready for payment: {matched_product}")
                        else:
                            logger.warning(f"Vision service returned status {vision_response.status_code}")
                
                # Fallback: recommend sample products if no match
                if not matched_product:
                    recommended_products = [
                        {"id": "prod_001", "name": "Sample Product", "price": 29.99, "url": "https://example.com/product/1"}
                    ]
                    response_text = "No pude identificar el producto exacto. ¿Te gustaría ver más opciones?"
                    
            except Exception as e:
                logger.error(f"Error in buying intent flow: {e}")
                response_text = "Hubo un problema al buscar el producto. Por favor intenta de nuevo."
        
        # Store chat message in Supabase if available
        if db_initialized:
            try:
                supabase = get_supabase_client()
                supabase.table("chat_messages").insert({
                    "user_id": payload.user_id,
                    "streamer": payload.streamer_id,
                    "message": payload.message,
                    "intent": intent,
                    "cantidad": cantidad,
                    "timestamp": timestamp
                }).execute()
            except Exception as e:
                logger.warning(f"Failed to store chat message in Supabase: {e}")
                # Continue anyway - DB failure shouldn't break the chat
        
        return ChatResponse(
            user_id=payload.user_id,
            streamer_id=payload.streamer_id,
            message=payload.message,
            intent=intent,
            cantidad=cantidad,
            timestamp=timestamp,
            matched_product=matched_product,
            recommended_products=recommended_products,
            response_text=response_text,
            payment_ready=payment_ready
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _queue_comment_internal(payload: IncomingComment) -> dict:
    """
    Internal function to queue a comment to Redis and Supabase.
    
    This function is reused by both HTTP POST /comments and WebSocket /ws/comments.
    
    Args:
        payload: Incoming comment with streamer, client, timestamp, message
    
    Returns:
        Dictionary with queuing details: ok, queued_to, stream, timestamp
        
    Raises:
        HTTPException: If Redis is unavailable
    """
    # Construct serializable payload
    comment = {
        "streamer": payload.streamer,
        "client": payload.client,
        "timestamp": payload.timestamp,
        "message": payload.message
    }
    
    list_key = f"chat:queue:{payload.streamer}:{payload.client}"
    
    # 1) Push to Redis global stream for auditing/consumer groups
    if not redis_client:
        logger.warning("Redis client not available: comment not enqueued")
        raise HTTPException(status_code=503, detail="Redis service unavailable")
    
    try:
        # XADD comments_stream * field1 value1 ...
        await redis_client.xadd("comments_stream", comment)
        
        # 2) RPUSH into per-client list
        await redis_client.rpush(list_key, json.dumps(comment))
        
        # Optionally set TTL to auto-expire empty queues (7 days)
        await redis_client.expire(list_key, 7 * 24 * 3600)
        
        logger.info(
            "Comment queued: streamer=%s client=%s stream=comments_stream list=%s",
            payload.streamer,
            payload.client,
            list_key
        )
    except Exception as e:
        logger.error("Failed to queue comment in Redis: %s", e)
        raise HTTPException(status_code=500, detail=f"Redis queuing failed: {e}")
    
    # 3) Store in Supabase for persistence (best-effort, non-blocking)
    if db_initialized:
        try:
            supabase = get_supabase_client()
            supabase.table("chat_messages").insert({
                "streamer": payload.streamer,
                "client": payload.client,
                "timestamp": payload.timestamp,
                "message": payload.message
            }).execute()
        except Exception as e:
            logger.warning("Failed to store comment in Supabase: %s", e)
            # Don't fail the request - Supabase is best-effort
    
    return {
        "ok": True,
        "queued_to": list_key,
        "stream": "comments_stream",
        "timestamp": payload.timestamp
    }


@app.post("/comments", response_model=CommentQueueResponse)
async def receive_comment(payload: IncomingComment):
    """
    HTTP endpoint: Receive incoming comments from TikTok/stream sources and queue them to Redis.
    
    Routes comments to:
      - Global Redis stream: "comments_stream" (for auditing/consumer groups)
      - Per-client Redis list: "chat:queue:{streamer}:{client}" (for per-client processing)
      - Supabase (for persistence)
    
    Args:
        payload: Incoming comment with streamer, client, timestamp, message
    
    Returns:
        CommentQueueResponse with queue details
    """
    try:
        result = await _queue_comment_internal(payload)
        return CommentQueueResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to receive comment via HTTP")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status")
async def service_status():
    """Get service status and configuration."""
    return {
        "service": "chat-product",
        "version": "1.0.0",
        "database": "connected" if db_initialized else "offline",
        "nlp_service": NLP_SERVICE_URL,
        "vision_service": VISION_SERVICE_URL,
        "redis_url": REDIS_URL
    }


@app.post("/process_queue", response_model=ProcessQueueResponse)
async def process_user_queue(payload: ProcessQueueRequest):
    """
    Process all messages in a user's queue to determine buying intent.
    
    Flow:
    1. Get all messages from Redis queue for this user
    2. Send ALL messages to NLP webhook for intent analysis
    3. If intent = yes, find product from live stream frame via vision service
    4. Clear processed messages from queue
    5. Return result with matched product if found
    
    Args:
        payload: ProcessQueueRequest with streamer_id and user_id
    
    Returns:
        ProcessQueueResponse with intent, matched product, and payment status
    """
    list_key = f"chat:queue:{payload.streamer_id}:{payload.user_id}"
    
    # Check Redis availability
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis service unavailable")
    
    try:
        # Step 1: Get all messages from user's queue
        messages_raw = await redis_client.lrange(list_key, 0, -1)
        
        if not messages_raw or len(messages_raw) == 0:
            return ProcessQueueResponse(
                user_id=payload.user_id,
                streamer_id=payload.streamer_id,
                messages_processed=0,
                intent="no",
                cantidad=0,
                matched_product=None,
                payment_ready=False,
                response_text="No hay mensajes en la cola para procesar."
            )
        
        # Parse messages and extract first timestamp
        messages = []
        first_timestamp = None
        for msg_raw in messages_raw:
            try:
                msg = json.loads(msg_raw)
                messages.append(msg.get("message", ""))
                # Capture the timestamp from the FIRST message (when buying intent started)
                if first_timestamp is None and msg.get("timestamp"):
                    first_timestamp = msg.get("timestamp")
            except json.JSONDecodeError:
                messages.append(str(msg_raw))
        
        # Fallback to current time if no timestamp found
        if first_timestamp is None:
            first_timestamp = datetime.utcnow().isoformat()
        
        logger.info(f"Processing {len(messages)} messages for user {payload.user_id}, first_timestamp: {first_timestamp}")
        
        # Step 2: Send ALL messages to NLP webhook for intent detection
        intent = "no"
        cantidad = 0
        
        try:
            # Combine all messages for context
            combined_messages = " | ".join(messages)
            
            async with httpx.AsyncClient(timeout=15.0) as client:
                webhook_response = await client.post(
                    N8N_WEBHOOK_URL,
                    json={"message": combined_messages},
                    headers={"Content-Type": "application/json"}
                )
                if webhook_response.status_code == 200:
                    result = webhook_response.json()
                    logger.info(f"Webhook response: {result}")
                    
                    # Parse response: [{"intent": "yes/no", "cantidad": int}]
                    if isinstance(result, list) and len(result) > 0:
                        first_item = result[0]
                        intent = first_item.get("intent", "no").lower()
                        cantidad = int(first_item.get("cantidad", 0))
                    elif isinstance(result, dict):
                        intent = result.get("intent", "no").lower()
                        cantidad = int(result.get("cantidad", 0))
                    
                    logger.info(f"Intent from NLP: {intent}, cantidad: {cantidad}")
                else:
                    logger.warning(f"Webhook returned status {webhook_response.status_code}")
        except Exception as e:
            logger.error(f"Failed to call NLP webhook: {e}")
        
        # Initialize response variables
        matched_product = None
        payment_ready = False
        response_text = "¿En qué puedo ayudarte?"
        
        # Step 3: If buying intent, find product from live stream frame
        if intent == "yes":
            try:
                frame_url = None
                supabase = get_supabase_client() if db_initialized else None
                
                # Get the frame closest to the FIRST message timestamp (when buying intent started)
                if supabase:
                    # Find frame with timestamp <= first_timestamp (closest before or at)
                    frames_resp = supabase.table("streamer_frames") \
                        .select("id,minio_url,frame_timestamp") \
                        .eq("streamer", payload.streamer_id) \
                        .lte("frame_timestamp", first_timestamp) \
                        .order("frame_timestamp", desc=True) \
                        .limit(1) \
                        .execute()
                    
                    if frames_resp.data and len(frames_resp.data) > 0:
                        frame_url = frames_resp.data[0].get("minio_url")
                        frame_ts = frames_resp.data[0].get("frame_timestamp")
                        logger.info(f"Found frame at {frame_ts} for first_timestamp {first_timestamp}: {frame_url}")
                    else:
                        # Fallback: get the earliest frame after first_timestamp
                        frames_resp = supabase.table("streamer_frames") \
                            .select("id,minio_url,frame_timestamp") \
                            .eq("streamer", payload.streamer_id) \
                            .gte("frame_timestamp", first_timestamp) \
                            .order("frame_timestamp", desc=False) \
                            .limit(1) \
                            .execute()
                        
                        if frames_resp.data and len(frames_resp.data) > 0:
                            frame_url = frames_resp.data[0].get("minio_url")
                            frame_ts = frames_resp.data[0].get("frame_timestamp")
                            logger.info(f"Fallback frame at {frame_ts} for first_timestamp {first_timestamp}: {frame_url}")
                
                # Call vision service with frame URL
                if frame_url:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        vision_response = await client.post(
                            f"{VISION_SERVICE_URL}/match_product",
                            json={
                                "frame_urls": [frame_url],
                                "streamer_id": payload.streamer_id
                            },
                            headers={"Content-Type": "application/json"}
                        )
                        if vision_response.status_code == 200:
                            vision_result = vision_response.json()
                            product_id = vision_result.get("productId")
                            logger.info(f"Vision matched product_id: {product_id}")
                            
                            # Get product details
                            if product_id and supabase:
                                product_resp = supabase.table("products") \
                                    .select("id,name,price,description,image_url") \
                                    .eq("id", product_id) \
                                    .limit(1) \
                                    .execute()
                                
                                if product_resp.data and len(product_resp.data) > 0:
                                    product = product_resp.data[0]
                                    matched_product = {
                                        "id": product.get("id"),
                                        "name": product.get("name"),
                                        "price": product.get("price"),
                                        "description": product.get("description"),
                                        "image_url": product.get("image_url"),
                                        "cantidad": cantidad,
                                        "total": float(product.get("price", 0)) * cantidad
                                    }
                                    payment_ready = True
                                    response_text = f"¡Encontré el producto! {product.get('name')} - ${product.get('price')}. ¿Deseas comprar {cantidad} unidad(es)?"
                
                if not matched_product:
                    response_text = "Detecté intención de compra pero no pude identificar el producto. ¿Podrías ser más específico?"
                    
            except Exception as e:
                logger.error(f"Error in buying intent flow: {e}")
                response_text = "Hubo un problema al buscar el producto. Intenta de nuevo."
        
        # Step 4: Clear processed messages from queue
        await redis_client.delete(list_key)
        logger.info(f"Cleared queue {list_key} after processing {len(messages)} messages")
        
        return ProcessQueueResponse(
            user_id=payload.user_id,
            streamer_id=payload.streamer_id,
            messages_processed=len(messages),
            intent=intent,
            cantidad=cantidad,
            matched_product=matched_product,
            payment_ready=payment_ready,
            response_text=response_text
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error processing queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8081,
        reload=False,
        log_level="info"
    )
