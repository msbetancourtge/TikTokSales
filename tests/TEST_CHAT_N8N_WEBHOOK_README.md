# Chat-Product N8N Webhook Tests

## Overview

This test suite validates the integration between the chat-product service and the n8n webhook for intent classification.

## Test Coverage

### Main Test Suite: `TestN8nWebhookIntegration`

1. **test_chat_endpoint_buy_intent_yes** - Verifies the `/chat` endpoint correctly handles "buy_intent: yes" response
2. **test_chat_endpoint_buy_intent_no** - Verifies the `/chat` endpoint correctly handles "buy_intent: no" response
3. **test_chat_endpoint_webhook_error_handling** - Tests graceful fallback when webhook times out
4. **test_chat_endpoint_webhook_non_200_status** - Tests handling of non-200 HTTP responses
5. **test_chat_endpoint_webhook_called_with_correct_payload** - Validates webhook is called with correct message
6. **test_chat_response_structure** - Ensures response includes all required fields
7. **test_chat_endpoint_webhook_url_from_env** - Verifies environment variable configuration

### Edge Cases: `TestN8nWebhookEdgeCases`

1. **test_chat_with_empty_webhook_response** - Tests handling of empty JSON responses
2. **test_chat_with_malformed_webhook_response** - Tests handling of invalid JSON
3. **test_chat_with_case_insensitive_buy_intent** - Verifies case-insensitive intent matching

## Running the Tests

### Run all webhook tests:
```bash
cd /Users/mikebetancourt/Documents/Hackathon/TikTokSales
pytest tests/test_chat_n8n_webhook.py -v
```

### Run specific test class:
```bash
pytest tests/test_chat_n8n_webhook.py::TestN8nWebhookIntegration -v
```

### Run specific test:
```bash
pytest tests/test_chat_n8n_webhook.py::TestN8nWebhookIntegration::test_chat_endpoint_buy_intent_yes -v
```

### Run with output capture disabled (see print statements):
```bash
pytest tests/test_chat_n8n_webhook.py -v -s
```

## Test Details

### Webhook Integration Flow

1. Client sends chat message to `/chat` endpoint
2. Service makes async HTTP POST to n8n webhook with message payload
3. Webhook responds with `{"buy_intent": "yes"|"no"}`
4. Service sets intent to "buy" (score 0.95) or "none" (score 0.0)
5. Response includes recommended products if intent is "buy"

### Mock Strategy

Tests use `unittest.mock` to:
- Mock the `httpx.AsyncClient` to intercept webhook calls
- Return predetermined webhook responses
- Simulate network errors and malformed responses
- Verify correct parameters are passed to webhook

### Environment Configuration

The n8n webhook URL is configurable via:
```python
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "http://72.61.76.44:5678/webhook-test/37b254d7-d925-4e3a-a725-edbbe4f225b8")
```

To override in tests or deployment:
```bash
export N8N_WEBHOOK_URL="http://your-custom-webhook:port/path"
```

## Expected Webhook Response Format

The n8n webhook should return JSON in this format:

**Success (Buy Intent):**
```json
{
  "buy_intent": "yes"
}
```

**No Intent:**
```json
{
  "buy_intent": "no"
}
```

## Troubleshooting

### Tests fail with "No module named 'app'"

Ensure you're running tests from the repository root:
```bash
cd /Users/mikebetancourt/Documents/Hackathon/TikTokSales
pytest tests/test_chat_n8n_webhook.py
```

### Tests hang or timeout

Check that the mock is properly configured. Tests should not make real HTTP calls.

### Import errors for FastAPI/Pydantic

Ensure test dependencies are installed:
```bash
pip install -r tests/requirements.txt
```
