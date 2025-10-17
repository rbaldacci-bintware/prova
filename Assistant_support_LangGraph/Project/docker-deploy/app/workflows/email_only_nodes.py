# app/workflows/email_only_nodes.py
"""
Esempio di workflow alternativo: invio email senza processing completo.
Utile per re-inviare email o inviare notifiche su conversazioni già processate.
"""
import os
import json
import logging
import requests
from ..state import GraphState
from ..internal_api_client import InternalApiClient

logger = logging.getLogger(__name__)
EMAIL_API_URL = os.getenv("EMAIL_API_URL", "http://localhost:5007")

def load_existing_transcript_node(state: GraphState) -> dict:
    """
    Carica una trascrizione esistente dal database se non presente nello state.
    Utile per workflow che partono da conversazioni già processate.
    """
    logger.info("--- NODO: CARICAMENTO TRASCRIZIONE ESISTENTE ---")
    
    # Se c'è già la trascrizione nello state, usala
    if state.get("transcript"):
        logger.info("✓ Trascrizione già presente nello state")
        return {}
    
    # Altrimenti carica dal database
    conversation_id = state.get("conversation_id")
    if not conversation_id:
        return {"error": "conversation_id mancante per caricare trascrizione"}
    
    config = state.get("config", {})
    api_client = InternalApiClient(config)
    
    # Chiamata API per recuperare trascrizione
    endpoint = f"{api_client.base_url}/api/internal/GetConversation/{conversation_id}"
    
    try:
        response = requests.get(
            endpoint,
            headers={"X-Api-Key": api_client.api_key},
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            transcript = data.get("transcribe", "")
            logger.info(f"✓ Trascrizione caricata: {len(transcript)} caratteri")
            return {"transcript": transcript}
        else:
            logger.error(f"Errore caricamento trascrizione: {response.status_code}")
            return {"error": f"Impossibile caricare trascrizione: {response.status_code}"}
            
    except Exception as e:
        logger.error(f"Eccezione caricamento trascrizione: {str(e)}")
        return {"error": str(e)}

def quick_email_node(state: GraphState) -> dict:
    """
    Versione semplificata del nodo email per invio rapido.
    """
    logger.info("--- NODO: INVIO EMAIL RAPIDO ---")
    
    scope = state.get("scope", [])
    if not scope:
        logger.info("Email non richiesta (scope vuoto)")
        return {"email_result": "SKIPPED_NO_SCOPE"}
    
    config = state.get("config", {})
    api_client = InternalApiClient(config)
    
    # Converti scope in lista
    scope_value = list(scope) if isinstance(scope, set) else scope
    if not isinstance(scope_value, list):
        scope_value = [scope_value] if scope_value else []
    
    # Prepara payload semplificato
    graph_payload = {
        "graph": {
            "edges": [],
            "nodes": [{
                "id": "email",
                "type": "tool",
                "plugin": "email",
                "function": "send_simple_notification",
                "outputKey": "emailResult",
                "parameters": {
                    "scope": "{{scope}}",
                    "conversationId": "{{conversationId}}",
                    "tenant_key": "{{tenant_key}}",
                    "transcript": "{{transcript}}"
                }
            }],
            "startNodeId": "email"
        },
        "input": "",
        "state": {
            "scope": scope_value,
            "conversationId": state.get("conversation_id", "none"),
            "tenant_key": state.get("tenant_key", "none"),
            "transcript": state.get("transcript", "none")
        }
    }
    
    headers = {
        'accept': 'text/plain',
        'X-Api-Key': api_client.api_key,
        'Content-Type': 'application/json'
    }
    
    try:
        response = requests.post(
            f"{EMAIL_API_URL}/api/Graph/run",
            json=graph_payload,
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            logger.info("✅ Email inviata con successo")
            return {"email_result": "SUCCESS", "email_response": response.text}
        else:
            logger.error(f"Errore invio email: {response.status_code}")
            return {"email_result": f"ERROR_{response.status_code}", "email_error": response.text}
            
    except Exception as e:
        logger.error(f"Eccezione invio email: {str(e)}")
        return {"email_result": "ERROR", "email_error": str(e)}

def notification_node(state: GraphState) -> dict:
    """
    Nodo per inviare notifiche generiche (es. Slack, Teams, etc.)
    """
    logger.info("--- NODO: INVIO NOTIFICA ---")
    
    notification_type = state.get("notification_type", "email")
    message = state.get("notification_message", "Elaborazione completata")
    
    # Implementa logica di notifica
    logger.info(f"Invio notifica {notification_type}: {message}")
    
    return {
        "notification_result": "SUCCESS",
        "notification_type": notification_type
    }

# Registra i nodi di questo modulo
WORKFLOW_NODES = {
    "load_transcript": load_existing_transcript_node,
    "quick_email": quick_email_node,
    "notify": notification_node
}