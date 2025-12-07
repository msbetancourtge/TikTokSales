"""
Complete TikTokSales Architecture & Data Flow Diagram

This file documents the entire system architecture and how data flows through it.
"""

ARCHITECTURE = """
╔════════════════════════════════════════════════════════════════════════════╗
║                     TIKTOKSALES SYSTEM ARCHITECTURE                        ║
╚════════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────────┐
│ TIKTOK / INSTAGRAM / YOUTUBE LIVE STREAMS                                   │
│ (Source of truth: real-time comments from viewers)                         │
└────────────────────────────┬────────────────────────────────────────────────┘
                             │ WebSocket or HTTP polling
                             │ Streamer: @user123, Client: viewer456
                             │ Message: "I want to buy this!"
                             ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                      CHAT-PRODUCT SERVICE (Port 8081)                        │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  HTTP POST /comments                    WebSocket /ws/comments             │
│  ├─ Accepts JSON payload                ├─ Real-time bidirectional        │
│  ├─ Validates via IncomingComment       ├─ Persistent connection          │
│  ├─ Auto-generates timestamp            ├─ Same queuing logic             │
│  └─ Returns queue confirmation          └─ Lower latency                  │
│                                                                              │
│  Internal: _queue_comment_internal()    (Shared logic for both endpoints)  │
│  ├─ XADD to Redis Stream (audit)                                           │
│  ├─ RPUSH to Redis List (worker queue)                                     │
│  ├─ INSERT to Supabase (persistence)                                       │
│  └─ Return confirmation to client                                          │
│                                                                              │
│  Environment: SUPABASE_URL, SUPABASE_SERVICE_KEY, REDIS_URL                │
└────────────┬─────────────────────────────────────────────┬──────────────────┘
             │                                             │
             │ XADD                                    RPUSH
             ▼                                             ▼
    ┌──────────────────────┐                  ┌──────────────────────────┐
    │   REDIS STREAM       │                  │  REDIS LISTS (Workers)   │
    │  comments_stream     │                  │  chat:queue:user:client  │
    │  (Audit Trail)       │                  │  (Per-client queues)     │
    │                      │                  │                          │
    │  Structure:          │                  │  Structure:              │
    │  ID: 1765081486-0    │                  │  Messages: [JSON, JSON]  │
    │  Fields:             │                  │  TTL: 7 days             │
    │  - streamer          │                  │  BLPOP timeout: 5s       │
    │  - client            │                  └──────────────────────────┘
    │  - timestamp         │                           │
    │  - message           │                        BLPOP
    │  - nlp_intent        │                           │
    │  - nlp_score         │                           ▼
    │                      │                  ┌──────────────────────────┐
    │  Use cases:          │                  │    WORKER SERVICE        │
    │  - Compliance audit  │                  │  (Background Processor)  │
    │  - Consumer groups   │                  │                          │
    │  - Replay/recovery   │                  │  Process flow:           │
    │  - Analytics         │                  │  1. Consume from queue   │
    │                      │                  │  2. Call NLP service     │
    └──────────────────────┘                  │  3. If buy intent:       │
             │                                 │     a. Call Vision svc   │
             │                                 │     b. If product match: │
             │                                 │        Call Ecommerce    │
             │                                 │                          │
             │                                 │  Error handling:         │
             │                                 │  - Retry logic           │
             │                                 │  - DLQ (dead letter)     │
             │                                 │  - Logging               │
             │                                 └──────────────────────────┘
             │                                            │
             │                   ┌────────────┬───────────┼─────────────┐
             │                   │            │           │             │
             ▼                   ▼            ▼           ▼             ▼
    ┌──────────────────┐ ┌────────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐
    │  SUPABASE (DB)   │ │ NLP SVC    │ │ VISION  │ │ECOMMERCE │ │ STRIPE   │
    │                  │ │ (Port 8001)│ │ SVC     │ │(Port 8082)│ │ (Payment)│
    │  Tables:         │ │            │ │(8002)   │ │          │ │          │
    │  ├─ chat_msgs    │ │ Input:     │ │ Input:  │ │ Input:   │ │ Input:   │
    │  ├─ products     │ │ {text: "..." }│ {       │ │ {        │ │ {        │
    │  ├─ orders       │ │            │ │ stream: │ │ product_ │ │ amount:  │
    │  ├─ streamers    │ │ Output:    │ │ "user", │ │ id,      │ │ "99.99", │
    │  ├─ matches      │ │ {intent:   │ │ ts:     │ │ buyer,   │ │ token:   │
    │  └─ mapping      │ │  "buy",    │ │ "2025.."} │ streamer, │ │ ".."     │
    │                  │ │ score:0.92 │ │ urls:[] │ │ qty:1    │ │          │
    │  Indexes:        │ │ }          │ │ }       │ │ }        │ │ Output:  │
    │  - streamer+ts   │ │            │ │ Output: │ │ Output:  │ │ {        │
    │  - client        │ │ Detection: │ │ {       │ │ {        │ │ txn_id:  │
    │  - intent        │ │ Keywords   │ │ product:│ │ order_id:│ │ "pi_...",│
    │  - status        │ │ + Scoring  │ │ "PRD-"  │ │"ORD-...",│ │ status:  │
    │                  │ │            │ │ score:  │ │ status:  │ │ "succ"   │
    │  For each msg:   │ │            │ │ 0.87    │ │ "pending"│ │ }        │
    │  ├─ inserted     │ │            │ │ }       │ │ }        │ │          │
    │  ├─ nlp_intent   │ │ Intents:   │ │         │ │ Actions: │ │ Actions: │
    │  ├─ nlp_score    │ │ - buy      │ │ CNN     │ │ ├─ Save  │ │ ├─ Verify│
    │  ├─ product_id   │ │ - question │ │ Model   │ │ │ order  │ │ │ card    │
    │  └─ order_id     │ │ - feedback │ │ on      │ │ ├─ Link  │ │ ├─ Charge│
    │                  │ │ - none     │ │ frames  │ │ │ to msg  │ │ │ card    │
    │                  │ │ - complain │ │         │ │ ├─ Notify│ │ ├─ Update│
    │  Relationships:  │ │            │ │ Matches │ │ │ streamer│ │ │ order   │
    │  ├─ chat→orders  │ │ Threshold: │ │ product │ │ └─ Send  │ │ └─ Emit  │
    │  ├─ orders→prod  │ │ score>0.5  │ │ from    │ │ to WA/SMS│ │ │ webhook │
    │  ├─ orders→user  │ │            │ │ product │ │          │ │          │
    │  └─ orders→stream│ │ Services:  │ │ catalog │ │ Services:│ │ Services:│
    │                  │ │ - OpenAI   │ │ by      │ │ - Twilio │ │ - Card   │
    │  APIs:           │ │ - Local ML │ │ timestamp│ │ (SMS/WA) │ │ - Auth   │
    │  - insert()      │ │ - spaCy    │ │ matching │ │ - Email  │ │ - 3DS    │
    │  - query()       │ │            │ │ .       │ │          │ │          │
    │  - update()      │ │ HTTP POST  │ │ HTTP    │ │ HTTP POST│ │ API Call │
    │  - delete()      │ │ localhost: │ │ POST    │ │ localhost:│ │ (python) │
    │                  │ │ 8001/...   │ │ local-  │ │ 8082/... │ │          │
    │  Security:       │ │            │ │ host:   │ │          │ │          │
    │  - Row-level SEC │ │ Timeout:   │ │ 8002/.. │ │ Timeout: │ │ Timeout: │
    │  - Encryption    │ │ 10s        │ │ Timeout:│ │ 10s      │ │ 30s      │
    │  - Caching       │ │            │ │ 15s     │ │          │ │          │
    └──────────────────┘ └────────────┘ └─────────┘ └──────────┘ └──────────┘
             ▲                   ▲            ▲
             │                   │            │
             └───────────────────┼────────────┘
                   INSERT/UPDATE │
                    on completion│
                                 │
                    ┌────────────▼──────────────┐
                    │   COMPLETE ORDER FLOW    │
                    │                          │
                    │ 1. Message arrives       │
                    │    ↓                     │
                    │ 2. Stored in chat_msgs   │
                    │    ↓                     │
                    │ 3. Queued to worker      │
                    │    ↓                     │
                    │ 4. NLP predicts intent   │
                    │    ↓                     │
                    │ 5. Update nlp_intent,    │
                    │    nlp_score             │
                    │    ↓                     │
                    │ 6. If "buy" score>0.5:  │
                    │    Call Vision service   │
                    │    ↓                     │
                    │ 7. Vision returns prod   │
                    │    ↓                     │
                    │ 8. Insert product_match │
                    │    ↓                     │
                    │ 9. If prod_score>0.7:   │
                    │    Call Ecommerce API    │
                    │    ↓                     │
                    │ 10. Create order in DB   │
                    │    ↓                     │
                    │ 11. Link msg→order       │
                    │    ↓                     │
                    │ 12. Call Stripe for pay  │
                    │    ↓                     │
                    │ 13. Insert notification  │
                    │    ↓                     │
                    │ 14. Send WhatsApp/SMS    │
                    │    ↓                     │
                    │ 15. COMPLETE ✓           │
                    └──────────────────────────┘


════════════════════════════════════════════════════════════════════════════════
                             DATA FLOW EXAMPLES
════════════════════════════════════════════════════════════════════════════════

EXAMPLE 1: Buy Intent (Happy Path)
──────────────────────────────────

TikTok Stream Event:
  Streamer: @fashionista_jane
  Viewer: @viewer_mike
  Timestamp: 2025-12-06 14:30:45.123456 UTC
  Comment: "OMG I love this jacket! I want to buy it now!"

[1] HTTP POST /comments (Chat-Product):
  Payload: {
    "streamer": "fashionista_jane",
    "client": "viewer_mike",
    "message": "OMG I love this jacket! I want to buy it now!"
  }
  
  Response: {
    "ok": true,
    "queued_to": "chat:queue:fashionista_jane:viewer_mike",
    "stream": "comments_stream",
    "timestamp": "2025-12-06T14:30:45.123456"
  }

[2] Redis (immediate):
  XADD comments_stream
    streamer "fashionista_jane"
    client "viewer_mike"
    message "OMG I love this jacket! I want to buy it now!"
    timestamp "2025-12-06T14:30:45.123456"
  → Returns: 1765081486123-0
  
  RPUSH chat:queue:fashionista_jane:viewer_mike
    {"streamer": "fashionista_jane", "client": "viewer_mike", ...}
  
  EXPIRE chat:queue:fashionista_jane:viewer_mike 604800  (7 days)

[3] Supabase INSERT (async):
  INSERT INTO chat_messages
    (streamer, client, timestamp, message)
  VALUES
    ('fashionista_jane', 'viewer_mike', '2025-12-06 14:30:45', 'OMG I love...')
  → id: 42

[4] Worker Service (BLPOP on queue):
  Consumes: {"streamer": "fashionista_jane", "client": "viewer_mike", ...}

[5] Call NLP Service:
  POST http://nlp-service:8001/predict_intent
  {
    "text": "OMG I love this jacket! I want to buy it now!"
  }
  
  Response: {
    "intent": "buy",
    "score": 0.94
  }
  
  UPDATE chat_messages SET nlp_intent='buy', nlp_score=0.94 WHERE id=42

[6] Since intent="buy" AND score=0.94 > 0.5:
  Call Vision Service:
  POST http://vision-service:8002/match_product
  {
    "streamer": "fashionista_jane",
    "timestamp": "2025-12-06T14:30:45.123456",
    "frame_urls": [
      "s3://stream-frames/fashionista_jane/14-30-45-001.jpg",
      "s3://stream-frames/fashionista_jane/14-30-45-002.jpg",
      "s3://stream-frames/fashionista_jane/14-30-45-003.jpg"
    ]
  }
  
  Response: {
    "productId": "SKU-BLUE-JACKET-M",
    "product_name": "Blue Denim Jacket",
    "score": 0.89,
    "price": 79.99
  }
  
  INSERT INTO product_matches
    (streamer, stream_timestamp, product_id, vision_score)
  VALUES
    ('fashionista_jane', '2025-12-06 14:30:45', 1, 0.89)
  → id: 567

[7] Since product_score=0.89 > 0.7:
  Call Ecommerce Service:
  POST http://ecommerce:8082/order/create
  {
    "product_id": "SKU-BLUE-JACKET-M",
    "buyer": "viewer_mike",
    "streamer": "fashionista_jane",
    "source": "tiktok_live",
    "quantity": 1
  }
  
  Response: {
    "order_id": "ORD-20251206-00123",
    "order_number": "ORD-20251206-00123",
    "status": "pending",
    "total_price": 79.99,
    "product_name": "Blue Denim Jacket"
  }
  
  INSERT INTO orders
    (order_number, product_id, buyer, streamer, source, status, total_price)
  VALUES
    ('ORD-20251206-00123', 1, 'viewer_mike', 'fashionista_jane', 'tiktok_live', 'pending', 79.99)
  → id: 999

[8] Link message to order:
  INSERT INTO chat_message_order_mapping
    (chat_message_id, order_id)
  VALUES
    (42, 999)
  
  Now can query: Which message led to which order? ORDER 999 ← MESSAGE 42

[9] Process payment (Stripe):
  POST https://api.stripe.com/v1/payment_intents
  {
    "amount": 7999,  // cents
    "currency": "usd",
    "metadata": {
      "order_id": "ORD-20251206-00123",
      "buyer": "viewer_mike",
      "streamer": "fashionista_jane"
    }
  }
  
  Response: {
    "id": "pi_1MsSdmEeYkS4J7jJb3p0Hcl9",
    "status": "succeeded",
    "client_secret": "pi_1Ms..._secret_...",
    "charges": {...}
  }
  
  UPDATE orders SET
    status='paid',
    payment_method='stripe',
    payment_id='pi_1MsSdmEeYkS4J7jJb3p0Hcl9'
  WHERE id=999

[10] Send WhatsApp confirmation:
  POST https://api.twilio.com/2010-04-01/Accounts/.../Messages
  {
    "Body": "Order ORD-20251206-00123 confirmed! Your Blue Denim Jacket ($79.99) will ship soon. Track: [link]",
    "To": "+1234567890",  // viewer_mike's WhatsApp number
    "MessagingServiceSid": "..."
  }
  
  Response: {"sid": "SM123456789", "status": "queued"}
  
  INSERT INTO payment_notifications
    (order_id, notification_type, recipient_number, message_sid, status)
  VALUES
    (999, 'whatsapp', '+1234567890', 'SM123456789', 'sent')

[11] Complete! Order flow:
  Message (42) → Chat Message
          ├─ NLP: "buy" (0.94)
          ├─ Vision: Product SKU-BLUE-JACKET-M (0.89)
          ├─ Order: ORD-20251206-00123 (999)
          ├─ Payment: Stripe pi_1Ms...
          ├─ Notification: WhatsApp SM123...
          └─ Streamer Commission: $79.99 × 10% = $8.00 earned

Final Database State:
  chat_messages[42] = {streamer, client, message, nlp_intent='buy', nlp_score=0.94}
  product_matches[567] = {product_id=1, vision_score=0.89}
  orders[999] = {order_number, product_id=1, buyer, streamer, status='paid'}
  chat_message_order_mapping = {chat_message_id=42, order_id=999}
  payment_notifications = {order_id=999, status='sent'}


EXAMPLE 2: Non-Buy Intent (Filtered Out)
─────────────────────────────────────────

TikTok Stream Event:
  Comment: "This is so cute! 💕"

[1] HTTP POST → Redis queuing (same as above)

[2] NLP Analysis:
  Input: "This is so cute! 💕"
  
  Response: {
    "intent": "feedback",
    "score": 0.72
  }
  
  Since intent != "buy", worker STOPS processing.
  
  UPDATE chat_messages SET nlp_intent='feedback', nlp_score=0.72
  (No Vision call, no order created)

Result:
  - Message stored in DB with intent="feedback"
  - No order created
  - No payment processed
  - Useful for analytics: "What did viewers think?"


════════════════════════════════════════════════════════════════════════════════
                              KEY METRICS
════════════════════════════════════════════════════════════════════════════════

Message → Order Conversion:
  - NLP filter: ~20% of messages have buy intent (intent="buy", score>0.5)
  - Vision filter: ~70% of buy messages lead to product match (score>0.7)
  - Overall conversion: ~14% of messages → orders

Performance SLA:
  - Message ingestion: < 100ms (HTTP POST)
  - Redis queuing: < 50ms
  - NLP inference: < 2s
  - Vision inference: < 5s
  - Ecommerce order: < 500ms
  - Payment processing: < 2s
  - Total (message → order): < 10s

Redis Memory (per 1000 messages):
  - Stream: ~50KB (one entry = ~50 bytes)
  - Per-client lists: ~100KB (one message = ~100 bytes)
  - Total: ~150KB per 1000 messages

Database Growth (per 1000 messages):
  - chat_messages: 1000 rows
  - product_matches: ~200 rows (20% buy intent)
  - orders: ~140 rows (70% of buy intents have match)
  - Notifications: ~140 rows
  - Total: ~1500 rows

Cost Estimate (per 1000 messages):
  - AWS S3 frames: $0.023 (if 1 MB per match)
  - NLP inference: $0.20 (if using API)
  - Vision inference: $0.50 (if using API)
  - Stripe fees: ~$1.40 (2.2% + $0.30 per order × 140 orders)
  - Twilio SMS: $0.07 (140 messages × $0.0075 each)
  Total: ~$2.40 per 1000 messages = $0.0024 per message

"""

if __name__ == "__main__":
    print(ARCHITECTURE)
