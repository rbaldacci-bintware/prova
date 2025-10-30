# app/internal_api_client.py - VERSIONE ASYNC
import os
import logging
from typing import Optional, Dict, Any
import httpx  # ✅ NUOVO: httpx invece di requests

logger = logging.getLogger(__name__)

class InternalApiClient:
    """Client asincrono per chiamare le API C# esistenti"""
    
    def __init__(self, config):
        self.config = config
        self.api_key = config.get("InternalStaticKey")
        if not self.api_key:
            raise ValueError("InternalStaticKey non configurata")
        
        self.logger = logging.getLogger(__name__)
        
        # URL base dalla configurazione
        self.base_url = config.get("RemoteApi", {}).get("BaseUrl", "http://localhost:5010")
        self.google_api_url = config.get("RemoteApi", {}).get("BaseUrlGoogleApi", "http://localhost:5020")
        self.file_service_url = config.get("RemoteApi", {}).get("BaseUrlFileService", "http://localhost:5019")
        
        # ✅ NUOVO: Timeout configurabili
        self.timeout = httpx.Timeout(120.0, connect=10.0)
    
    def _get_headers(self):
        return {
            "X-Api-Key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
    
    async def post_json(self, endpoint: str, data: Dict) -> Optional[Dict]:
        """POST JSON async to endpoint"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    endpoint,
                    json=data,
                    headers=self._get_headers()
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    self.logger.error(f"API error: {response.status_code} - {response.text}")
                    return None
        except httpx.TimeoutException:
            self.logger.error(f"Timeout calling API: {endpoint}")
            return None
        except Exception as e:
            self.logger.error(f"Exception calling API: {str(e)}")
            return None
    
    async def get_bytes(self, endpoint: str) -> bytes:
        """GET bytes async from endpoint"""
        headers = {
            "X-Api-Key": self.api_key,
            "Accept": "application/octet-stream"
        }
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(endpoint, headers=headers)
            response.raise_for_status()
            return response.content
    
    async def put_json(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """PUT async to endpoint"""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                response = await client.put(
                    endpoint,
                    params=params,
                    headers={"X-Api-Key": self.api_key}
                )
                
                if response.status_code == 200:
                    return {"status": "success"}
                else:
                    self.logger.error(f"PUT error: {response.status_code}")
                    return None
        except Exception as e:
            self.logger.error(f"Exception in PUT: {str(e)}")
            return None