# TikTokSales/worker.py
import asyncio
import json
import os
import logging
import httpx
import redis.asyncio as aioredis
from datetime import datetime
from io import BytesIO

from minio import Minio
from minio.error import S3Error

logger = logging.getLogger("worker")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
NLP_SERVICE_URL = os.getenv("NLP_SERVICE_URL", "http://nlp-service:8001")
VISION_SERVICE_URL = os.getenv("VISION_SERVICE_URL", "http://vision-service:8002")
ECOMMERCE_URL = os.getenv("ECOMMERCE_URL", "http://ecommerce:8082")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# Frame capture endpoint template (should return image bytes). Example: http://stream-capture/{streamer}/frame
FRAME_CAPTURE_URL_TEMPLATE = os.getenv("FRAME_CAPTURE_URL_TEMPLATE", "http://vision-service:8002/capture_frame?streamer={streamer}")

# MinIO settings
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minio")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minio123")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "tiktoksales-frames")
MINIO_USE_SSL = os.getenv("MINIO_USE_SSL", "False").lower() == "true"

minio_client = None

redis_client = None

async def connect_redis():
    global redis_client
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    await redis_client.ping()
    logger.info("Redis connected: %s", REDIS_URL)


def init_minio():
    global minio_client
    try:
        minio_client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_USE_SSL
        )
        # Ensure bucket exists (synchronous call)
        if not minio_client.bucket_exists(MINIO_BUCKET):
            minio_client.make_bucket(MINIO_BUCKET)
            logger.info("Created MinIO bucket: %s", MINIO_BUCKET)
        else:
            logger.info("MinIO bucket exists: %s", MINIO_BUCKET)
    except Exception as e:
        logger.warning("Failed to initialize MinIO client: %s", e)
        minio_client = None

async def process_comment(comment: dict):
    """Process a single comment through NLP → Vision → Order pipeline."""
    logger.debug("Processing comment: %s", comment)
    
    # Step 1: NLP Intent Detection
    nlp_result = {"intent": "none", "score": 0.0}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{NLP_SERVICE_URL}/predict_intent",
                json={"text": comment.get("message", "")},
                timeout=10.0
            )
            nlp_result = response.json()
            logger.info("NLP result for '%s': %s", comment.get("message"), nlp_result)
    except Exception as e:
        logger.warning("NLP service failed: %s", e)
    
    # Step 2: Check if purchase intent + confidence threshold
    if nlp_result.get("intent") == "buy" and nlp_result.get("score", 0) > 0.5:
        logger.info("🛒 BUY intent detected (score: %.2f)", nlp_result.get("score", 0))
        
        # Step 3: Vision Service - Match Product
        match_result = {"productId": None, "score": 0.0}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # TODO: Fetch frame URLs from Supabase based on comment timestamp
                response = await client.post(
                    f"{VISION_SERVICE_URL}/match_product",
                    json={"frame_urls": []},  # Pass actual URLs
                    timeout=15.0
                )
                match_result = response.json()
                logger.info("Vision match: %s", match_result)
        except Exception as e:
            logger.warning("Vision service failed: %s", e)
        
        # Step 4: Create Order if Product Match + Stock Available
        if match_result.get("productId") and match_result.get("score", 0) > 0.7:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    order_payload = {
                        "product_id": match_result["productId"],
                        "buyer": comment.get("client"),
                        "streamer": comment.get("streamer"),
                        "source": "tiktok_live"
                    }
                    response = await client.post(
                        f"{ECOMMERCE_URL}/order/create",
                        json=order_payload,
                        timeout=10.0
                    )
                    order = response.json()
                    logger.info("✅ Order created: %s", order)
            except Exception as e:
                logger.warning("Order creation failed: %s", e)
        else:
            logger.info("No product match or confidence too low: %s", match_result)
    else:
        logger.debug("No buy intent: %s", nlp_result)

async def get_active_queue_keys():
    """Scan Redis for active comment queue keys."""
    try:
        cursor = "0"
        keys = []
        while True:
            cursor, batch = await redis_client.scan(
                cursor, match="chat:queue:*", count=100
            )
            keys.extend(batch)
            if cursor == "0":
                break
        return keys
    except Exception as e:
        logger.error("Failed to scan keys: %s", e)
        return []

async def worker_loop():
    """
    Main worker loop: consume comments from Redis queues and process.
    
    Strategy: SCAN for active queue keys, BLPOP with 5s timeout.
    Handles graceful shutdown and error recovery.
    """
    logger.info("🚀 Worker started")
    
    while True:
        try:
            keys = await get_active_queue_keys()
            
            if not keys:
                logger.debug("No active queues, sleeping 1s")
                await asyncio.sleep(1)
                continue
            
            logger.debug("Found %d active queues", len(keys))
            
            # BLPOP: block on multiple keys, timeout 5s
            result = await redis_client.blpop(*keys, timeout=5)
            
            if result:
                key, raw_comment = result
                try:
                    comment = json.loads(raw_comment)
                    logger.info(
                        "📨 Processing from %s: streamer=%s client=%s",
                        key, comment.get("streamer"), comment.get("client")
                    )
                    await process_comment(comment)
                except json.JSONDecodeError as e:
                    logger.error("Invalid JSON in queue %s: %s", key, e)
            else:
                # Timeout - no messages available
                await asyncio.sleep(0.1)
                
        except Exception as e:
            logger.exception("Worker loop error")
            await asyncio.sleep(1)


async def fetch_streamers_from_supabase() -> list:
    """Fetch LIVE streamer usernames from Supabase REST API."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.debug("Supabase config not provided; using STREAMERS env or empty list")
        env_list = os.getenv("STREAMERS", "")
        return [s.strip() for s in env_list.split(",") if s.strip()]

    # Only fetch streamers that are currently live
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/streamers?select=username&is_live=eq.true"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Accept": "application/json"
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                data = r.json()
                live_streamers = [row.get("username") for row in data if row.get("username")]
                if live_streamers:
                    logger.info("Found %d live streamer(s): %s", len(live_streamers), live_streamers)
                return live_streamers
            else:
                logger.warning("Failed to fetch streamers from Supabase: %s %s", r.status_code, r.text)
                return []
    except Exception as e:
        logger.warning("Error fetching streamers: %s", e)
        return []


def upload_bytes_to_minio(content: bytes, streamer: str, timestamp: datetime, content_type: str = "image/jpeg") -> dict:
    """Upload raw bytes to MinIO and return object info."""
    if not minio_client:
        raise RuntimeError("MinIO client not initialized")

    ts = timestamp.strftime("%Y%m%d_%H%M%S")
    ext = "jpg"
    object_name = f"frames/{streamer}/{ts}.{ext}"
    try:
        minio_client.put_object(
            bucket_name=MINIO_BUCKET,
            object_name=object_name,
            data=BytesIO(content),
            length=len(content),
            content_type=content_type
        )
        url = f"minio://{MINIO_BUCKET}/{object_name}"
        return {"minio_object": object_name, "minio_url": url}
    except S3Error as e:
        logger.error("MinIO upload error: %s", e)
        raise


async def save_frame_record_to_supabase(streamer: str, timestamp: datetime, minio_url: str, minio_object: str):
    """Insert a frame record into Supabase via REST API."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.debug("Supabase not configured; skipping DB insert for frame")
        return None

    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/streamer_frames"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    payload = {
        "streamer": streamer,
        "frame_timestamp": timestamp.isoformat(),
        "minio_url": minio_url,
        "minio_object": minio_object
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code in (200, 201):
                logger.info("Saved frame metadata to Supabase for %s @ %s", streamer, timestamp)
                return r.json()
            else:
                logger.warning("Failed to save frame to Supabase: %s %s", r.status_code, r.text)
                return None
    except Exception as e:
        logger.warning("Error saving frame to Supabase: %s", e)
        return None


async def collect_frames_loop(poll_interval: int = 10):
    """Periodically capture frames per streamer and store them in MinIO and Supabase."""
    logger.info("Frame collector started (interval=%ss)", poll_interval)
    while True:
        try:
            streamers = await fetch_streamers_from_supabase()
            if not streamers:
                logger.debug("No streamers found; sleeping")
                await asyncio.sleep(poll_interval)
                continue

            for streamer in streamers:
                try:
                    capture_url = FRAME_CAPTURE_URL_TEMPLATE.format(streamer=streamer)
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        r = await client.get(capture_url)
                        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                            timestamp = datetime.utcnow()
                            content_type = r.headers.get("content-type")
                            blob = r.content
                            # Upload to MinIO (blocking put_object through helper)
                            try:
                                info = upload_bytes_to_minio(blob, streamer, timestamp, content_type)
                                await save_frame_record_to_supabase(streamer, timestamp, info["minio_url"], info["minio_object"])
                            except Exception as e:
                                logger.warning("Failed to upload/save frame for %s: %s", streamer, e)
                        else:
                            logger.debug("No image captured for %s (status=%s)", streamer, r.status_code)
                except Exception as e:
                    logger.warning("Collector error for streamer %s: %s", streamer, e)

            await asyncio.sleep(poll_interval)
        except Exception as e:
            logger.exception("Frame collector loop error")
            await asyncio.sleep(poll_interval)

async def main():
    try:
        await connect_redis()
        init_minio()

        # Run worker loop and frame collector concurrently
        worker_task = asyncio.create_task(worker_loop())
        collector_task = asyncio.create_task(collect_frames_loop())

        await asyncio.gather(worker_task, collector_task)
    except KeyboardInterrupt:
        logger.info("Worker shutting down...")
    except Exception as e:
        logger.exception("Fatal error: %s", e)
        raise
    finally:
        if redis_client:
            await redis_client.close()

if __name__ == "__main__":
    asyncio.run(main())