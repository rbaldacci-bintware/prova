# app/internal_api_client.py - VERSIONE PULITA (SOLO ENV VARS)
import os
import logging
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger(__name__)

class InternalApiClient:
    """
    Client asincrono centralizzato per TUTTE le chiamate API esterne.
    
    ✅ USA SOLO VARIABILI D'AMBIENTE (config.json rimosso per URL)
    
    Gestisce:
    - API C# interna (base_url)
    - Google API / Gemini (google_api_url)
    - File Service (file_service_url)
    - Email Service (email_api_url)
    """
    
    def __init__(self, config):
        self.config = config
        self.api_key = config.get("InternalStaticKey")
        if not self.api_key:
            raise ValueError("InternalStaticKey non configurata")
        
        self.logger = logging.getLogger(__name__)
        
        # ✅ SOLO VARIABILI D'AMBIENTE
        # Se non impostate, usa valori di default per sviluppo locale
        
        # API C# interna
        self.base_url = os.getenv(
            "INTERNAL_API_URL",
            "http://localhost:5010"  # Default per dev locale
        )
        
        # Google API / Gemini
        self.google_api_url = os.getenv(
            "GOOGLE_API_URL",
            "http://localhost:5020"  # Default per dev locale
        )
        
        # File Service
        self.file_service_url = os.getenv(
            "FILE_API_URL",
            "http://localhost:5019"  # Default per dev locale
        )
        
        # Email Service
        self.email_api_url = os.getenv(
            "EMAIL_API_URL",
            "http://localhost:5007"  # Default per dev locale
        )
        
        # Timeout configurabili
        self.timeout = httpx.Timeout(120.0, connect=10.0)
        
        # Log della configurazione
        self._log_configuration()
    
    def _log_configuration(self):
        """Log della configurazione URL (per debug)"""
        self.logger.info("=== API Client Configuration ===")
        self.logger.info(f"Base URL (C# API):     {self.base_url}")
        self.logger.info(f"Google API URL:        {self.google_api_url}")
        self.logger.info(f"File Service URL:      {self.file_service_url}")
        self.logger.info(f"Email Service URL:     {self.email_api_url}")
        self.logger.info("================================")
    
    def _get_headers(self, accept: str = "application/json"):
        """Headers standard con API key"""
        return {
            "X-Api-Key": self.api_key,
            "Accept": accept,
            "Content-Type": "application/json"
        }
    
    # ==========================================
    # METODI HTTP GENERICI
    # ==========================================
    
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
    
    # ==========================================
    # METODI SPECIFICI PER SERVIZI
    # ==========================================
    
    async def mark_stretch_completed(
        self, 
        conversation_id: str, 
        stretch_type: str
    ) -> bool:
        """
        Marca uno stretch come completato nell'API C#.
        
        Args:
            conversation_id: ID conversazione
            stretch_type: "TRASCRIZIONE" | "ANALISI" | etc.
        """
        if not conversation_id:
            self.logger.warning(f"[{stretch_type}] conversation_id mancante")
            return False
        
        url = f"{self.base_url}/api/InternalConversazione/UpdateConversazioneStretchCompleted"
        params = {"convName": conversation_id, "ind_type": stretch_type}
        
        try:
            self.logger.info(f"[{stretch_type}] Marcatore per: {conversation_id}")
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.put(url, params=params, headers={"X-Api-Key": self.api_key})
            
            if response.status_code == 200:
                self.logger.info(f"✅ [{stretch_type}] Marcatore inserito")
                return True
            else:
                self.logger.error(f"❌ [{stretch_type}] Errore: {response.status_code}")
                return False
                
        except httpx.TimeoutException:
            self.logger.error(f"⏱️ [{stretch_type}] Timeout")
            return False
        except Exception as e:
            self.logger.error(f"❌ [{stretch_type}] Errore: {str(e)}")
            return False
    
    async def download_file(self, location: str, file_name: str) -> Optional[bytes]:
        """
        Scarica un file dal File Service.
        
        Args:
            location: Cartella nel file service
            file_name: Nome del file
            
        Returns:
            Bytes del file o None se errore
        """
        url = f"{self.file_service_url}/api/files/{location}/{file_name}"
        
        try:
            self.logger.info(f"Download file: {file_name}")
            return await self.get_bytes(url)
        except Exception as e:
            self.logger.error(f"Errore download {file_name}: {e}")
            return None
    
    async def send_email_via_graph(
        self,
        graph_payload: Dict,
        timeout: float = 180.0
    ) -> Optional[Dict]:
        """
        Invia email tramite Email API (Graph API).
        
        Args:
            graph_payload: Payload del grafo email
            timeout: Timeout in secondi
            
        Returns:
            Response dict o None
        """
        url = f"{self.email_api_url}/api/Graph/run"
        headers = {
            'accept': 'text/plain',
            'X-Api-Key': self.api_key,
            'Content-Type': 'application/json'
        }
        
        try:
            self.logger.info(f"Invio email tramite: {url}")
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=graph_payload, headers=headers)
            
            if response.status_code == 200:
                self.logger.info("✅ Email inviata con successo")
                return {
                    "status": "SUCCESS",
                    "response": response.text
                }
            else:
                self.logger.error(f"❌ Errore invio email: {response.status_code}")
                return {
                    "status": f"ERROR_{response.status_code}",
                    "error": response.text
                }
                
        except httpx.TimeoutException:
            self.logger.error("⏱️ Timeout invio email")
            return {"status": "TIMEOUT"}
        except Exception as e:
            self.logger.error(f"❌ Errore invio email: {str(e)}")
            return {"status": "ERROR", "error": str(e)}