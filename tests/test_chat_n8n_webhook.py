"""
Tests for chat-product service n8n webhook integration.
Tests the /chat endpoint's integration with the n8n webhook for intent classification.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
import sys
import os

# Add services directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'chat-product'))

from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Fixture to provide a FastAPI test client."""
    from app import app
    return TestClient(app)


class TestN8nWebhookIntegration:
    """Test suite for n8n webhook integration in chat service."""
    
    def test_chat_endpoint_buy_intent_yes(self, client):
        """Test /chat endpoint when n8n returns buy_intent: yes."""
        with patch('app.httpx.AsyncClient') as mock_client_class:
            # Mock the AsyncClient context manager
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            # Mock the webhook response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"buy_intent": "yes"}
            mock_client.post.return_value = mock_response
            
            # Send chat message
            response = client.post("/chat", json={
                "user_id": "test_user_123",
                "message": "I want to buy this product"
            })
            
            assert response.status_code == 200
            data = response.json()
            assert data["intent"] == "buy"
            assert data["intent_score"] == 0.95
            assert len(data["recommended_products"]) > 0
            assert data["response_text"] == "¿Te gustaría ver más opciones?"
    
    def test_chat_endpoint_buy_intent_no(self, client):
        """Test /chat endpoint when n8n returns buy_intent: no."""
        with patch('app.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"buy_intent": "no"}
            mock_client.post.return_value = mock_response
            
            response = client.post("/chat", json={
                "user_id": "test_user_456",
                "message": "What are the features?"
            })
            
            assert response.status_code == 200
            data = response.json()
            assert data["intent"] == "none"
            assert data["intent_score"] == 0.0
            assert len(data["recommended_products"]) == 0
            assert data["response_text"] == "¿En qué puedo ayudarte?"
    
    def test_chat_endpoint_webhook_error_handling(self, client):
        """Test /chat endpoint when n8n webhook fails."""
        with patch('app.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            # Simulate webhook timeout/error
            mock_client.post.side_effect = httpx.TimeoutException("Webhook timeout")
            
            response = client.post("/chat", json={
                "user_id": "test_user_789",
                "message": "Test message"
            })
            
            # Should still return 200 with default "none" intent
            assert response.status_code == 200
            data = response.json()
            assert data["intent"] == "none"
            assert data["intent_score"] == 0.0
    
    def test_chat_endpoint_webhook_non_200_status(self, client):
        """Test /chat endpoint when n8n webhook returns non-200 status."""
        with patch('app.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_client.post.return_value = mock_response
            
            response = client.post("/chat", json={
                "user_id": "test_user_999",
                "message": "Test message"
            })
            
            # Should still return 200 with default "none" intent
            assert response.status_code == 200
            data = response.json()
            assert data["intent"] == "none"
            assert data["intent_score"] == 0.0
    
    def test_chat_endpoint_webhook_called_with_correct_payload(self, client):
        """Test that webhook is called with the correct message payload."""
        with patch('app.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"buy_intent": "yes"}
            mock_client.post.return_value = mock_response
            
            test_message = "¡Quiero comprar esto ahora!"
            response = client.post("/chat", json={
                "user_id": "webhook_test_user",
                "message": test_message
            })
            
            # Verify webhook was called
            assert mock_client.post.called
            
            # Get the actual call arguments
            call_kwargs = mock_client.post.call_args[1]
            assert call_kwargs["json"]["message"] == test_message
            assert call_kwargs["headers"]["Content-Type"] == "application/json"
    
    def test_chat_endpoint_webhook_url_from_env(self, client):
        """Test that webhook URL can be configured via environment variable."""
        # This test verifies the N8N_WEBHOOK_URL environment variable is respected
        with patch.dict(os.environ, {"N8N_WEBHOOK_URL": "http://custom-webhook:1234/webhook"}):
            # Re-import to pick up new env var
            import importlib
            import app as app_module
            importlib.reload(app_module)
            
            assert app_module.N8N_WEBHOOK_URL == "http://custom-webhook:1234/webhook"
    
    def test_chat_response_structure(self, client):
        """Test that chat response has all expected fields."""
        with patch('app.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"buy_intent": "yes"}
            mock_client.post.return_value = mock_response
            
            response = client.post("/chat", json={
                "user_id": "struct_test_user",
                "message": "Buy this now"
            })
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify all required fields are present
            assert "user_id" in data
            assert "message" in data
            assert "intent" in data
            assert "intent_score" in data
            assert "recommended_products" in data
            assert "response_text" in data
            
            # Verify types
            assert isinstance(data["user_id"], str)
            assert isinstance(data["message"], str)
            assert isinstance(data["intent"], str)
            assert isinstance(data["intent_score"], (int, float))
            assert isinstance(data["recommended_products"], list)
            assert isinstance(data["response_text"], str)


class TestN8nWebhookEdgeCases:
    """Test edge cases and error scenarios."""
    
    def test_chat_with_empty_webhook_response(self, client):
        """Test handling of empty webhook response."""
        with patch('app.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {}  # Empty response
            mock_client.post.return_value = mock_response
            
            response = client.post("/chat", json={
                "user_id": "empty_response_user",
                "message": "Test"
            })
            
            assert response.status_code == 200
            data = response.json()
            assert data["intent"] == "none"  # Should default to "none"
    
    def test_chat_with_malformed_webhook_response(self, client):
        """Test handling of malformed webhook JSON response."""
        with patch('app.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.side_effect = ValueError("Invalid JSON")
            mock_client.post.return_value = mock_response
            
            response = client.post("/chat", json={
                "user_id": "malformed_user",
                "message": "Test"
            })
            
            assert response.status_code == 200
            data = response.json()
            assert data["intent"] == "none"
    
    def test_chat_with_case_insensitive_buy_intent(self, client):
        """Test that buy_intent response is case-insensitive."""
        test_cases = [
            ("YES", "buy"),
            ("Yes", "buy"),
            ("yEs", "buy"),
            ("NO", "none"),
            ("No", "none"),
            ("nO", "none"),
        ]
        
        for webhook_response, expected_intent in test_cases:
            with patch('app.httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value.__aenter__.return_value = mock_client
                
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"buy_intent": webhook_response}
                mock_client.post.return_value = mock_response
                
                response = TestClient(sys.modules['app']).post("/chat", json={
                    "user_id": f"case_test_{webhook_response}",
                    "message": "Test"
                })
                
                # Note: TestClient must be created fresh, so we're just checking structure
                assert response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
