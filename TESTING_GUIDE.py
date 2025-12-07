#!/usr/bin/env python3
"""
Quick reference guide for TikTokSales testing and schema.

Shows how to:
1. Query the database
2. Debug Redis queues
3. Test individual services
4. Monitor the pipeline
"""

import json
from datetime import datetime

print("""
╔════════════════════════════════════════════════════════════════════════════╗
║                   TIKTOKSALES QUICK REFERENCE GUIDE                        ║
╚════════════════════════════════════════════════════════════════════════════╝

═══════════════════════════════════════════════════════════════════════════════
1. TESTING THE PIPELINE
═══════════════════════════════════════════════════════════════════════════════

START ALL SERVICES:
  cd infra
  docker compose up -d
  docker compose ps          # Verify all running

RUN ALL TESTS:
  cd tests
  chmod +x run_tests.sh
  ./run_tests.sh

RUN SPECIFIC TEST:
  ./run_tests.sh TestChatEndpoint
  ./run_tests.sh test_full_pipeline_happy_path
  ./run_tests.sh TestNLPIntegration

VIEW LOGS:
  docker compose logs chat-product -f
  docker compose logs worker -f
  docker compose logs nlp-service -f
  docker compose logs vision-service -f
  docker compose logs ecommerce -f

═══════════════════════════════════════════════════════════════════════════════
2. TESTING INDIVIDUAL SERVICES
═══════════════════════════════════════════════════════════════════════════════

CHAT-PRODUCT SERVICE (8081):
  # Health check
  curl http://localhost:8081/health
  
  # Send message via HTTP
  curl -X POST http://localhost:8081/comments \\
    -H "Content-Type: application/json" \\
    -d '{
      "streamer": "tiktok_user",
      "client": "web_user",
      "message": "I want to buy this!"
    }'

NLP SERVICE (8001):
  # Health check
  curl http://localhost:8001/health
  
  # Predict intent
  curl -X POST http://localhost:8001/predict_intent \\
    -H "Content-Type: application/json" \\
    -d '{"text": "I want to buy this product now!"}'

VISION SERVICE (8002):
  # Health check
  curl http://localhost:8002/health
  
  # Match product
  curl -X POST http://localhost:8002/match_product \\
    -H "Content-Type: application/json" \\
    -d '{
      "streamer": "tiktok_user",
      "timestamp": "2025-12-06T14:30:45.123456",
      "frame_urls": []
    }'

ECOMMERCE SERVICE (8082):
  # Health check
  curl http://localhost:8082/health
  
  # Create order
  curl -X POST http://localhost:8082/order/create \\
    -H "Content-Type: application/json" \\
    -d '{
      "product_id": "PROD-12345",
      "buyer": "web_user",
      "streamer": "tiktok_user",
      "source": "tiktok_live",
      "quantity": 1
    }'

═══════════════════════════════════════════════════════════════════════════════
3. DEBUGGING REDIS QUEUES
═══════════════════════════════════════════════════════════════════════════════

REDIS COMMANDS:
  # Connect to Redis
  redis-cli -h localhost -p 6379
  
  # Check all queue keys
  KEYS "chat:queue:*"
  
  # Get queue length for specific client
  LLEN "chat:queue:tiktok_user:web_user"
  
  # View all messages in queue (non-destructive)
  LRANGE "chat:queue:tiktok_user:web_user" 0 -1
  
  # View one message (peek)
  LRANGE "chat:queue:tiktok_user:web_user" -1 -1
  
  # Consume one message (destructive - like worker does)
  LPOP "chat:queue:tiktok_user:web_user"
  
  # Check global stream for audit trail
  XLEN "comments_stream"
  XRANGE "comments_stream" - +
  XREVRANGE "comments_stream" + - COUNT 5
  
  # Clear a queue (for testing)
  DEL "chat:queue:tiktok_user:web_user"
  DEL "comments_stream"
  
  # Check TTL on queue
  TTL "chat:queue:tiktok_user:web_user"

═══════════════════════════════════════════════════════════════════════════════
4. DATABASE SCHEMA DEPLOYMENT
═══════════════════════════════════════════════════════════════════════════════

1. Go to: https://supabase.com/dashboard/project/{your-project}
2. Navigate to: SQL Editor
3. Copy all migrations from schema.py
4. Run in order:
   - MIGRATION_001_CHAT_MESSAGES
   - MIGRATION_002_PRODUCTS
   - MIGRATION_003_PRODUCT_MATCHES
   - MIGRATION_004_ORDERS
   - MIGRATION_005_CHAT_MESSAGE_TO_ORDER
   - MIGRATION_006_PAYMENT_NOTIFICATIONS
   - MIGRATION_007_STREAMERS
   - MIGRATION_008_NLP_INTENTS

Or run programmatically:
  python schema.py > migrations.sql
  # Then paste into Supabase SQL editor

═══════════════════════════════════════════════════════════════════════════════
5. MANUAL PIPELINE TEST
═══════════════════════════════════════════════════════════════════════════════

STEP 1: Send message
  curl -X POST http://localhost:8081/comments \\
    -H "Content-Type: application/json" \\
    -d '{
      "streamer": "tiktok_user_123",
      "client": "web_client_456",
      "message": "I want to buy this product now!"
    }'
  
  Expected response:
    {
      "ok": true,
      "queued_to": "chat:queue:tiktok_user_123:web_client_456",
      "stream": "comments_stream",
      "timestamp": "2025-12-06T14:30:45.123456"
    }

STEP 2: Check Redis stream
  redis-cli XREVRANGE "comments_stream" + - COUNT 1
  
  Expected: Message in stream with timestamp

STEP 3: Check per-client queue
  redis-cli LLEN "chat:queue:tiktok_user_123:web_client_456"
  redis-cli LRANGE "chat:queue:tiktok_user_123:web_client_456" -1 -1
  
  Expected: 1 message in queue (JSON format)

STEP 4: NLP intent detection
  curl -X POST http://localhost:8001/predict_intent \\
    -H "Content-Type: application/json" \\
    -d '{"text": "I want to buy this product now!"}'
  
  Expected: {"intent": "buy", "score": 0.85+}

STEP 5: Vision product matching
  curl -X POST http://localhost:8002/match_product \\
    -H "Content-Type: application/json" \\
    -d '{
      "streamer": "tiktok_user_123",
      "timestamp": "2025-12-06T14:30:45.123456",
      "frame_urls": []
    }'
  
  Expected: {"productId": "PROD-XXXXX", "score": 0.8+}

STEP 6: Create order
  curl -X POST http://localhost:8082/order/create \\
    -H "Content-Type: application/json" \\
    -d '{
      "product_id": "PROD-12345",
      "buyer": "web_client_456",
      "streamer": "tiktok_user_123",
      "source": "tiktok_live",
      "quantity": 1
    }'
  
  Expected: {"order_id": "ORD-XXXXX", "status": "pending", ...}

═══════════════════════════════════════════════════════════════════════════════
6. DATABASE QUERIES
═══════════════════════════════════════════════════════════════════════════════

Go to: https://supabase.com/dashboard/project/{your-project} → SQL Editor

VIEW ALL CHAT MESSAGES:
  SELECT streamer, client, timestamp, message, nlp_intent, nlp_score
  FROM chat_messages
  ORDER BY timestamp DESC
  LIMIT 10;

VIEW BUY INTENT MESSAGES:
  SELECT streamer, client, timestamp, message, nlp_score
  FROM chat_messages
  WHERE nlp_intent = 'buy' AND nlp_score > 0.5
  ORDER BY timestamp DESC;

VIEW ALL ORDERS:
  SELECT o.id, o.order_number, o.buyer, o.streamer, p.name, o.status
  FROM orders o
  JOIN products p ON o.product_id = p.id
  ORDER BY o.created_at DESC;

VIEW ORDERS BY STREAMER:
  SELECT streamer, COUNT(*) as order_count, SUM(total_price) as revenue
  FROM orders
  WHERE status != 'cancelled'
  GROUP BY streamer
  ORDER BY revenue DESC;

TRACE MESSAGE TO ORDER:
  SELECT cm.streamer, cm.client, cm.message, cm.nlp_intent,
         o.order_number, o.status, p.name, o.total_price
  FROM chat_messages cm
  JOIN chat_message_order_mapping cmom ON cm.id = cmom.chat_message_id
  JOIN orders o ON cmom.order_id = o.id
  JOIN products p ON o.product_id = p.id
  ORDER BY cm.timestamp DESC;

═══════════════════════════════════════════════════════════════════════════════
7. MONITORING & METRICS
═══════════════════════════════════════════════════════════════════════════════

DOCKER STATS:
  docker stats --no-stream

SERVICE LOGS WITH TIMESTAMPS:
  docker compose logs --timestamps chat-product | tail -20
  docker compose logs --timestamps worker | tail -20

REDIS MEMORY USAGE:
  redis-cli INFO memory
  redis-cli DBSIZE

QUEUE BACKLOG SIZE:
  redis-cli KEYS "chat:queue:*" | wc -l
  # Sum of all queue lengths
  for key in $(redis-cli KEYS "chat:queue:*"); do
    echo -n "$key: "
    redis-cli LLEN "$key"
  done

TOTAL MESSAGES IN STREAM:
  redis-cli XLEN "comments_stream"

═══════════════════════════════════════════════════════════════════════════════
8. COMMON ISSUES & SOLUTIONS
═══════════════════════════════════════════════════════════════════════════════

ISSUE: Connection refused on 8081
  SOLUTION: Make sure chat-product container is running
    docker compose logs chat-product
    docker compose restart chat-product

ISSUE: NLP service timeout
  SOLUTION: Check if nlp-service is loaded and ready
    curl -v http://localhost:8001/health
    docker compose logs nlp-service

ISSUE: Redis connection errors
  SOLUTION: Check Redis is running and accepting connections
    redis-cli ping
    docker compose restart redis

ISSUE: Supabase connection errors
  SOLUTION: Check environment variables in .env
    echo $SUPABASE_URL
    echo $SUPABASE_SERVICE_KEY
    # Make sure they're set before starting services

ISSUE: Queue not being consumed
  SOLUTION: Start the worker service
    docker compose up -d worker
    docker compose logs worker -f

═══════════════════════════════════════════════════════════════════════════════
9. TEST DATA
═══════════════════════════════════════════════════════════════════════════════

BUY INTENT MESSAGES (score > 0.8):
  - "I want to buy this product now!"
  - "How much is it? I'll take it"
  - "Can I purchase this right now?"
  - "Add to cart please"
  - "I'm buying this!"

QUESTION MESSAGES (score > 0.7):
  - "What's the price?"
  - "Is this available in my size?"
  - "How long is the shipping?"
  - "What's the material?"

FEEDBACK MESSAGES (score > 0.6):
  - "This looks amazing!"
  - "I love this product"
  - "This is terrible"

NO INTENT MESSAGES (score < 0.3):
  - "LOL 😂"
  - "Nice stream today"
  - "See you next time"

═══════════════════════════════════════════════════════════════════════════════
10. DOCKER COMPOSE COMMANDS
═══════════════════════════════════════════════════════════════════════════════

START ALL SERVICES:
  docker compose up -d

STOP ALL SERVICES:
  docker compose down

VIEW STATUS:
  docker compose ps

VIEW LOGS:
  docker compose logs -f
  docker compose logs chat-product -f
  docker compose logs worker -f

REBUILD SERVICE:
  docker compose build --no-cache chat-product
  docker compose up -d chat-product

REMOVE ALL VOLUMES (WARNING: Data loss):
  docker compose down -v

DEBUG SPECIFIC CONTAINER:
  docker exec -it infra-chat-product-1 bash
  docker logs infra-chat-product-1 --tail 50 -f

═══════════════════════════════════════════════════════════════════════════════

Next Steps:
  1. Run: cd tests && ./run_tests.sh
  2. Check: tests/README.md for detailed test documentation
  3. Deploy: Database schema to Supabase (schema.py)
  4. Monitor: docker compose logs -f
  5. Debug: Use commands above to troubleshoot

Questions? Check:
  - services/chat-product/app.py
  - services/worker/worker.py
  - services/nlp-service/app.py
  - services/vision-service/app.py
  - services/ecommerce/app.py

═══════════════════════════════════════════════════════════════════════════════
""")

# Generate example curl commands
print("\n" + "="*80)
print("COPY-PASTE CURL COMMANDS")
print("="*80 + "\n")

examples = {
    "Send Buy Intent Message": """
curl -X POST http://localhost:8081/comments \\
  -H "Content-Type: application/json" \\
  -d '{
    "streamer": "tiktok_user_123",
    "client": "web_client_456",
    "message": "I want to buy this product now!"
  }'
""",
    "Check NLP Intent": """
curl -X POST http://localhost:8001/predict_intent \\
  -H "Content-Type: application/json" \\
  -d '{"text": "I want to buy this product now!"}'
""",
    "Match Product": """
curl -X POST http://localhost:8002/match_product \\
  -H "Content-Type: application/json" \\
  -d '{
    "streamer": "tiktok_user_123",
    "timestamp": "2025-12-06T14:30:45.123456",
    "frame_urls": []
  }'
""",
    "Create Order": """
curl -X POST http://localhost:8082/order/create \\
  -H "Content-Type: application/json" \\
  -d '{
    "product_id": "PROD-12345",
    "buyer": "web_client_456",
    "streamer": "tiktok_user_123",
    "source": "tiktok_live",
    "quantity": 1
  }'
"""
}

for name, cmd in examples.items():
    print(f"{name}:")
    print(cmd)
    print()
