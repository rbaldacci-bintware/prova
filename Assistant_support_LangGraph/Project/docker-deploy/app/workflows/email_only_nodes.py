# app/workflows/email_only_nodes.py - VERSIONE REFACTORED (NO URL HARDCODED)
"""
Workflow alternativo: invio email senza processing completo.
Utile per re-inviare email o inviare notifiche su conversazioni già processate.
"""
import json
import logging
import httpx
from ..state import GraphState
from ..internal_api_client import InternalApiClient

logger = logging.getLogger(__name__)

# ✅ RIMOSSO: EMAIL_API_URL hardcoded
# Ora gestito tramite InternalApiClient


async def load_existing_transcript_node(state: GraphState) -> dict:
    """Carica trascrizione esistente dal database (async)"""
    logger.info("--- NODO: CARICAMENTO TRASCRIZIONE (ASYNC) ---")
    
    if state.get("transcript"):
        logger.info("✓ Trascrizione già presente")
        return {}
    
    conversation_id = state.get("conversation_id")
    if not conversation_id:
        return {"error": "conversation_id mancante"}
    
    config = state.get("config", {})
    api_client = InternalApiClient(config)
    
    # ✅ USA URL CENTRALIZZATO
    endpoint = f"{api_client.base_url}/api/internal/GetConversation/{conversation_id}"
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                endpoint,
                headers={"X-Api-Key": api_client.api_key}
            )
        
        if response.status_code == 200:
            data = response.json()
            transcript = data.get("transcribe", "")
            logger.info(f"✓ Trascrizione caricata: {len(transcript)} caratteri")
            return {"transcript": transcript}
        else:
            logger.error(f"Errore caricamento: {response.status_code}")
            return {"error": f"Impossibile caricare: {response.status_code}"}
            
    except Exception as e:
        logger.error(f"Eccezione: {str(e)}")
        return {"error": str(e)}


async def quick_email_node(state: GraphState) -> dict:
    """Invio email rapido (async)"""
    logger.info("--- NODO: INVIO EMAIL RAPIDO (ASYNC) ---")
    
    scope = state.get("scope", [])
    if not scope:
        return {"email_result": "SKIPPED_NO_SCOPE"}
    
    config = state.get("config", {})
    api_client = InternalApiClient(config)
    
    scope_value = list(scope) if isinstance(scope, set) else scope
    if not isinstance(scope_value, list):
        scope_value = [scope_value] if scope_value else []
    
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
    
    # ✅ USA METODO CENTRALIZZATO
    result = await api_client.send_email_via_graph(graph_payload, timeout=30.0)
    
    if result and result.get("status") == "SUCCESS":
        return {
            "email_result": "SUCCESS",
            "email_response": result.get("response")
        }
    else:
        return {
            "email_result": result.get("status", "ERROR"),
            "email_error": result.get("error", "Unknown error")
        }


async def notification_node(state: GraphState) -> dict:
    """Invia notifiche generiche (async)"""
    logger.info("--- NODO: INVIO NOTIFICA (ASYNC) ---")
    
    notification_type = state.get("notification_type", "email")
    message = state.get("notification_message", "Elaborazione completata")
    
    logger.info(f"Notifica {notification_type}: {message}")
    
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