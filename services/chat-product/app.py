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
    """Chat message payload."""
    user_id: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1, max_length=2000)
    
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
    message: str
    intent: str  # "yes" or "no" - buying intent from webhook
    cantidad: int
    timestamp: str
    recommended_products: list = []
    response_text: str


class CommentQueueResponse(BaseModel):
    """Response after queuing a comment."""
    ok: bool
    queued_to: str
    stream: str = "comments_stream"
    timestamp: str


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
                    
                    # Parse Gemini model response structure:
                    # [{content: {parts: [{text: "{\"intencion_compra\": \"yes\", \"cantidad\": 1}"}]}}]
                    try:
                        # Handle array response from Gemini
                        if isinstance(result, list) and len(result) > 0:
                            content = result[0].get("content", {})
                            parts = content.get("parts", [])
                            if parts and len(parts) > 0:
                                text_json = parts[0].get("text", "{}")
                                # Parse the JSON string inside text
                                parsed = json.loads(text_json)
                                intent = parsed.get("intencion_compra").lower()
                                cantidad = int(parsed.get("cantidad", 0))
                        # Handle direct object response (fallback)
                        elif isinstance(result, dict):
                            text_block = result.get("text", {})
                            if isinstance(text_block, str):
                                parsed = json.loads(text_block)
                                intent = parsed.get("intencion_compra").lower()
                                cantidad = int(parsed.get("cantidad", 0))
                            else:
                                intent = text_block.get("intencion_compra").lower()
                                cantidad = int(text_block.get("cantidad", 0))
                        
                        logger.info(f"Intent classification from n8n: intent={intent}, cantidad={cantidad}")
                    except (json.JSONDecodeError, KeyError, TypeError) as parse_err:
                        logger.warning(f"Failed to parse webhook response: {parse_err}")
                        intent = "no"
                        cantidad = 0
                else:
                    logger.warning(f"n8n webhook returned status {webhook_response.status_code}")
        except Exception as e:
            logger.error(f"Failed to call n8n webhook for intent classification: {e}")
            intent = "no"
            cantidad = 0
        
        # Product recommendations if buying intent detected
        recommended_products = []
        if intent == "yes":
            recommended_products = [
                {
                    "id": "prod_001",
                    "name": "Sample Product",
                    "price": 29.99,
                    "url": "https://example.com/product/1"
                }
            ]
        
        response_text = "¿Te gustaría ver más opciones?" if intent == "yes" else "¿En qué puedo ayudarte?"
        
        # Store chat message in Supabase if available
        if db_initialized:
            try:
                supabase = get_supabase_client()
                supabase.table("chat_messages").insert({
                    "user_id": payload.user_id,
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
            message=payload.message,
            intent=intent,
            cantidad=cantidad,
            timestamp=timestamp,
            recommended_products=recommended_products,
            response_text=response_text
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8081,
        reload=False,
        log_level="info"
    )
