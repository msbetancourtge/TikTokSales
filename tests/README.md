# TikTokSales Integration Tests

Complete test suite for the end-to-end live shopping pipeline.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    TIKTOK / LIVE STREAM SOURCE                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │ (WebSocket or polling)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                  CHAT-PRODUCT SERVICE (8081)                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ HTTP POST /comments OR WebSocket /ws/comments           │  │
│  │ Receives: {streamer, client, timestamp, message}        │  │
│  └──────────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
    ┌──────────────────┐    ┌──────────────────────┐
    │ REDIS STREAM     │    │ REDIS LIST (per user)│
    │ comments_stream  │    │ chat:queue:*:*       │
    │ (audit trail)    │    │ (worker consumes)    │
    └──────────────────┘    └──────────────────────┘
                                      │
                                      ▼
                        ┌──────────────────────────┐
                        │   WORKER SERVICE         │
                        │ (processes queue async)  │
                        └──────────────────────────┘
                           │      │      │
                ┌──────────┘      │      └──────────┐
                ▼                 ▼                  ▼
        ┌────────────────┐ ┌────────────────┐ ┌─────────────────┐
        │ NLP Service    │ │ Vision Service │ │ Ecommerce Svc   │
        │ (8001)         │ │ (8002)         │ │ (8082)          │
        │                │ │                │ │                 │
        │ predict_intent │ │ match_product  │ │ order/create    │
        │ Returns: BUY?  │ │ Returns: Prod# │ │ Stripe Payment  │
        │                │ │                │ │ WhatsApp notify │
        └────────────────┘ └────────────────┘ └─────────────────┘
                                                      │
                                                      ▼
                                            ┌──────────────────┐
                                            │ SUPABASE (DB)    │
                                            │ - orders table   │
                                            │ - chat_messages  │
                                            │ - products       │
                                            └──────────────────┘
```

## Test Suites

### 1. TestChatEndpoint
Tests the HTTP/WebSocket message ingestion endpoints.

**Tests:**
- `test_health_check`: Verify chat-product service is running
- `test_http_comment_endpoint`: Send message via HTTP, verify queuing
- `test_websocket_comment_endpoint`: Structure verification for WebSocket

**What it validates:**
- Endpoint accepts valid JSON payloads
- Returns success response with queue confirmation
- Message fields: streamer, client, message are required
- Timestamp auto-generated if not provided

**Sample request:**
```json
{
  "streamer": "tiktok_live_user",
  "client": "web_user_001",
  "message": "I want to buy this product now!"
}
```

**Sample response:**
```json
{
  "ok": true,
  "queued_to": "chat:queue:tiktok_live_user:web_user_001",
  "stream": "comments_stream",
  "timestamp": "2025-12-06T14:30:45.123456"
}
```

### 2. TestRedisQueueing
Tests message persistence in Redis data structures.

**Tests:**
- `test_message_in_redis_stream`: Message appears in global stream for audit
- `test_message_in_per_client_list`: Message appears in per-client queue
- `test_redis_list_ttl`: Queue has 7-day expiration TTL

**What it validates:**
- Message routing to Redis stream (XADD)
- Message routing to per-client list (RPUSH)
- JSON serialization/deserialization
- TTL set correctly (604800s = 7 days)

**Data structures checked:**
```
Redis Stream: comments_stream
  └─ All messages for audit/consumer groups

Redis Lists: chat:queue:{streamer}:{client}
  └─ Per-client queues for worker processing
  └─ TTL: 7 days
```

### 3. TestNLPIntegration
Tests NLP service intent detection.

**Tests:**
- `test_nlp_service_health`: Verify NLP service is running
- `test_nlp_buy_intent_detection`: Classify message as "buy" intent
- `test_nlp_no_buy_intent`: Reject non-buy messages

**What it validates:**
- NLP service /predict_intent endpoint works
- Intent classification (buy, question, none, feedback, complaint)
- Confidence scores are 0-1 range
- High confidence (>0.5) for clear buy intent messages

**Sample request:**
```json
{
  "text": "I want to buy this product now!"
}
```

**Sample response:**
```json
{
  "intent": "buy",
  "score": 0.92
}
```

### 4. TestVisionIntegration
Tests Vision service for product matching from stream.

**Tests:**
- `test_vision_service_health`: Verify Vision service is running
- `test_vision_product_matching`: Match product from streamer+timestamp

**What it validates:**
- Vision service /match_product endpoint works
- Returns productId and confidence score
- Can receive streamer username and timestamp
- Score is 0-1 range

**Sample request:**
```json
{
  "streamer": "tiktok_live_user",
  "timestamp": "2025-12-06T14:30:45.123456",
  "frame_urls": ["s3://bucket/frame1.jpg", "s3://bucket/frame2.jpg"]
}
```

**Sample response:**
```json
{
  "productId": "PROD-12345",
  "score": 0.87,
  "product_name": "Limited Edition Sneaker"
}
```

### 5. TestEcommerceIntegration
Tests order creation endpoint.

**Tests:**
- `test_ecommerce_health`: Verify Ecommerce service is running
- `test_order_creation`: Create order with product, buyer, streamer

**What it validates:**
- Order creation endpoint accepts required fields
- Returns order ID on success
- Connects buyer with streamer for commission tracking
- Source field tracks platform (tiktok_live, instagram_live, etc)

**Sample request:**
```json
{
  "product_id": "PROD-12345",
  "buyer": "web_user_001",
  "streamer": "tiktok_live_user",
  "source": "tiktok_live",
  "quantity": 1
}
```

**Sample response:**
```json
{
  "order_id": "ORD-20251206-00001",
  "status": "pending",
  "total_price": 99.99
}
```

### 6. TestWorkerQueueProcessing
Tests worker service consuming messages from Redis.

**Tests:**
- `test_worker_consumes_queue`: Simulate worker BLPOP and message processing

**What it validates:**
- Messages removed from queue after processing (LPOP)
- Queue becomes empty after consumption
- JSON payload integrity preserved

**Flow:**
1. Add message to queue (RPUSH)
2. Simulate worker consuming (LPOP)
3. Verify queue empty

### 7. TestFullEndToEndPipeline
Complete integration test of entire system.

**Tests:**
- `test_full_pipeline_happy_path`: Full flow from message to order

**What it validates (6 stages):**

1. **Health Checks**: All services running
   - Chat-product (8081)
   - NLP Service (8001)
   - Vision Service (8002)
   - Ecommerce (8082)
   - Redis (6379)

2. **Message Ingestion**: Message sent via HTTP
   - Endpoint returns success
   - Message queued to specific client queue

3. **Redis Stream Verification**: Message in audit trail
   - Stream contains message
   - Can read with XREVRANGE

4. **Per-Client Queue**: Message in worker queue
   - Per-client list has message
   - Message JSON intact

5. **NLP Processing**: Intent detection
   - Buy intent detected (score > 0.5)
   - Message triggers purchase flow

6. **Vision + Ecommerce**: Product match and order
   - Vision service returns productId
   - Ecommerce creates order
   - Order linked to buyer and streamer

## Running the Tests

### Prerequisites
```bash
# 1. Start all services
cd infra
docker compose up -d

# 2. Wait for services to be ready
sleep 10

# 3. Verify services are running
docker compose ps
```

### Run All Tests
```bash
cd tests
chmod +x run_tests.sh
./run_tests.sh
```

### Run Specific Test Class
```bash
./run_tests.sh TestChatEndpoint
./run_tests.sh TestRedisQueueing
./run_tests.sh TestNLPIntegration
./run_tests.sh TestVisionIntegration
./run_tests.sh TestEcommerceIntegration
./run_tests.sh TestWorkerQueueProcessing
./run_tests.sh TestFullEndToEndPipeline
```

### Run Specific Test
```bash
./run_tests.sh test_health_check
./run_tests.sh test_http_comment_endpoint
./run_tests.sh test_message_in_redis_stream
./run_tests.sh test_full_pipeline_happy_path
```

### Run with Verbose Output
```bash
python -m pytest test_full_pipeline.py::TestChatEndpoint -v -s
```

## Expected Test Output

```
=== test session starts ===
platform darwin -- Python 3.11.x, pytest-7.4.3
collected 15 items

test_full_pipeline.py::TestChatEndpoint::test_health_check PASSED
test_full_pipeline.py::TestChatEndpoint::test_http_comment_endpoint PASSED
test_full_pipeline.py::TestRedisQueueing::test_message_in_redis_stream PASSED
test_full_pipeline.py::TestRedisQueueing::test_message_in_per_client_list PASSED
test_full_pipeline.py::TestRedisQueueing::test_redis_list_ttl PASSED
test_full_pipeline.py::TestNLPIntegration::test_nlp_service_health PASSED
test_full_pipeline.py::TestNLPIntegration::test_nlp_buy_intent_detection PASSED
test_full_pipeline.py::TestNLPIntegration::test_nlp_no_buy_intent PASSED
test_full_pipeline.py::TestVisionIntegration::test_vision_service_health PASSED
test_full_pipeline.py::TestVisionIntegration::test_vision_product_matching PASSED
test_full_pipeline.py::TestEcommerceIntegration::test_ecommerce_health PASSED
test_full_pipeline.py::TestEcommerceIntegration::test_order_creation PASSED
test_full_pipeline.py::TestWorkerQueueProcessing::test_worker_consumes_queue PASSED
test_full_pipeline.py::TestFullEndToEndPipeline::test_full_pipeline_happy_path PASSED

======= 15 passed in 12.34s =======
```

## Troubleshooting

### Services not running
```bash
# Check service status
cd infra && docker compose ps

# View service logs
docker compose logs chat-product
docker compose logs nlp-service
docker compose logs vision-service
docker compose logs ecommerce
```

### Redis connection failed
```bash
# Check Redis is running
redis-cli ping

# Check Redis has data
redis-cli KEYS "chat:queue:*"
redis-cli XLEN "comments_stream"
```

### NLP/Vision service timeout
```bash
# Check service is listening
curl -X POST http://localhost:8001/health
curl -X POST http://localhost:8002/health

# Check service logs
docker compose logs nlp-service
docker compose logs vision-service
```

### Supabase connection issues
```bash
# Check environment variables
echo $SUPABASE_URL
echo $SUPABASE_SERVICE_KEY

# Test connection manually
# (See db.py in services for connection logic)
```

## Database Schema Migration

Before running tests, deploy the schema:

```bash
# 1. Go to Supabase Console → SQL Editor
# 2. Run each migration from schema.py

# Or programmatically:
python ../schema.py | copy-to-supabase-sql-editor
```

**Tables created:**
- `chat_messages`: All incoming messages
- `products`: Product catalog
- `product_matches`: Vision service matches
- `orders`: Customer orders
- `chat_message_order_mapping`: Traceability
- `payment_notifications`: Audit trail
- `streamers`: Influencer profiles
- `nlp_intents`: Intent taxonomy

## Next Steps

1. **Run the full test suite**: `./run_tests.sh`
2. **Review test output** for any failures
3. **Deploy database schema** to Supabase
4. **Add real NLP/Vision models** to services
5. **Implement worker service** for background processing
6. **Test with real TikTok data** via streaming SDK

## Performance Benchmarks

Target metrics:
- Message ingestion: < 100ms
- Redis queuing: < 50ms
- NLP inference: < 2s (depends on model)
- Vision inference: < 5s (depends on model/frames)
- Order creation: < 500ms
- End-to-end (message → order): < 10s

---

**Last updated**: 2025-12-06
**Status**: Ready for testing
