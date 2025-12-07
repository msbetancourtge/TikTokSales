# TikTokSales/worker.py
import asyncio
import json
import os
import logging
import httpx
import redis.asyncio as aioredis
from datetime import datetime

logger = logging.getLogger("worker")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
NLP_SERVICE_URL = os.getenv("NLP_SERVICE_URL", "http://nlp-service:8001")
VISION_SERVICE_URL = os.getenv("VISION_SERVICE_URL", "http://vision-service:8002")
ECOMMERCE_URL = os.getenv("ECOMMERCE_URL", "http://ecommerce:8082")

redis_client = None

async def connect_redis():
    global redis_client
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    await redis_client.ping()
    logger.info("Redis connected: %s", REDIS_URL)

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

async def main():
    try:
        await connect_redis()
        await worker_loop()
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