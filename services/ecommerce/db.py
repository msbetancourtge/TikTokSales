"""
Supabase database client and utilities.
"""
import os
import logging
from typing import Optional
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# Supabase configuration from environment
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """
    Get or create Supabase client singleton.
    
    Returns:
        Supabase client instance
        
    Raises:
        ValueError: If SUPABASE_URL or SUPABASE_SERVICE_KEY not set
    """
    global _client
    
    if _client is not None:
        return _client
    
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.warning("Supabase credentials not configured. Database operations will fail.")
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables must be set")
    
    try:
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        logger.info("Supabase client initialized successfully")
        return _client
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
        raise


def initialize_supabase() -> bool:
    """
    Initialize Supabase connection on startup.
    
    Returns:
        True if successful, False if credentials not configured
    """
    try:
        get_supabase_client()
        return True
    except ValueError:
        # Credentials not configured - this is ok for development
        logger.warning("Supabase not configured - running in offline mode")
        return False
    except Exception as e:
        logger.error(f"Supabase initialization failed: {e}")
        return False
