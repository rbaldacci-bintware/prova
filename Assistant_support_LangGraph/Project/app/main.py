# app/main.py - VERSIONE CON SUPPORTO WORKFLOW DINAMICI
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Union

from .graph import dynamic_graph, prepare_workflow_steps
from .state import GraphState
from .configuration import initialize_configuration
from .workflows.registry import workflow_registry

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Inizializza configurazione
config = None
try:
    config = initialize_configuration("config.json")
    print("✅ Configurazione caricata con successo")
except Exception as e:
    print(f"⚠️ Errore inizializzazione configurazione: {str(e)}")

api = FastAPI(
    title="LangGraph Dynamic Workflow API",
    description="API con supporto per workflow dinamici multi-tenant",
    version="2.0.0",
)

# ===== MODELLI PYDANTIC =====

class WorkflowRequest(BaseModel):
    """Modello per richiesta con workflow dinamico"""
    workflow: Optional[Union[str, List[str]]] = "full"  # Nome preset o lista custom
    state: dict  # Stato iniziale

# ===== ENDPOINTS =====

@api.get("/")
async def root():
    """Endpoint di benvenuto"""
    return {
        "message": "LangGraph Dynamic Workflow API",
        "version": "2.0",
        "available_workflows": list(workflow_registry.get_all_workflows().keys()),
        "available_nodes": list(workflow_registry.get_all_nodes().keys())
    }

@api.post("/api/graph/run")
async def run_dynamic_workflow(request: WorkflowRequest):
    """
    Endpoint universale per eseguire workflow dinamici.
    
    Input JSON:
    {
      "workflow": "email_only",  // Nome preset o ["nodo1", "nodo2"] o ometti per "full"
      "state": {
        "location": "...",
        "inbound": "...",
        // ... altri campi
      }
    }
    """
    if not config:
        raise HTTPException(status_code=500, detail="Configurazione non inizializzata")
    
    try:
        # Estrai parametri
        input_state = request.state
        workflow_spec = request.workflow
        
        # Prepara i passi del workflow
        steps = prepare_workflow_steps(workflow_spec)
        
        if not steps:
            raise HTTPException(
                status_code=400, 
                detail="Nessun passo valido nel workflow richiesto"
            )
        
        logger.info(f"🚀 Avvio workflow: {workflow_spec}")
        logger.info(f"📋 Passi da eseguire: {steps}")
        
        # Prepara stato iniziale
        initial_state: GraphState = {
            # Campi base
            "messages": [],
            "audio_file_paths": [],
            "transcript": input_state.get("transcript", ""),
            "analysis_prompt": input_state.get("analysis_prompt"),
            # Identificazione
            "tenant_key": input_state.get("tenant_key"),
            "conversation_id": input_state.get("conversationId"),
            "co_code": input_state.get("co_code"),
            "orgn_code": input_state.get("orgn_code"),
            "user_id": input_state.get("user_id"),
            "caller_id": input_state.get("caller_id"),
            "scope": input_state.get("scope", []),
            "id_assistito": input_state.get("id_assistito"),
            
            # File storage
            "location": input_state.get("location"),
            "inbound": input_state.get("inbound"),
            "outbound": input_state.get("outbound"),
            "project_name": input_state.get("project_name"),
            "knowledge_base_files": input_state.get("knowledge_base_files", []),
            "output_mapping": input_state.get("output_mapping"),
            
            # Configurazione
            "config": {
                "InternalStaticKey": config["InternalStaticKey"],
                "RemoteApi": {
                    "BaseUrl": config.get("RemoteApi.BaseUrl", "http://localhost:5010"),
                    "BaseUrlGoogleApi": config.get("RemoteApi.BaseUrlGoogleApi", "http://localhost:5020"),
                    "BaseUrlFileService": config.get("FileApiBaseUrl", "http://localhost:5019")
                }
            },
            
            # Controllo del flusso
            "steps": steps,
            "current_step_index": 0,
            "execution_trace": [],
            "skip_remaining": False,
            "error": None,
            
            # Risultati inizializzati
            "persistence_result": None,
            "email_result": None,
            "suggestions": None,
            "action_plan": None,
            "tokens_used": 0,
            "cost_usd": 0.0,
            "analysis_saved": False,
            "final_status": None
        }
        
        # Esegui il workflow
        final_state = await dynamic_graph.ainvoke(initial_state)
        
        # Costruisci risposta
        return {
            "success": not bool(final_state.get("error")),
            "workflow_requested": workflow_spec,
            "workflow_executed": steps,
            "execution_trace": final_state.get("execution_trace", []),
            "state": {
                "conversation_id": final_state.get("conversation_id"),
                "transcript": final_state.get("transcript", ""),
                "persistence_result": final_state.get("persistence_result"),
                "email_result": final_state.get("email_result"),
                "tokens_used": final_state.get("tokens_used", 0),
                "cost_usd": final_state.get("cost_usd", 0.0),
                "analysis": {
                    "clusters": final_state.get("cluster_analysis", {}),
                    "interaction": final_state.get("interaction_analysis", {}),
                    "patterns": final_state.get("patterns_insights", {})
                } if final_state.get("cluster_analysis") else None,
                "suggestions": final_state.get("suggestions", {}),
                "final_status": final_state.get("final_status", "COMPLETED")
            },
            "error": final_state.get("error")
        }
        
    except Exception as e:
        logger.error(f"Errore nel workflow: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@api.get("/api/workflows")
async def get_available_workflows():
    """
    Restituisce informazioni sui workflow disponibili.
    """
    all_workflows = workflow_registry.get_all_workflows()
    all_nodes = workflow_registry.get_all_nodes()
    
    return {
        "workflows": {
            name: {
                "steps": info["steps"],
                "description": info.get("description", ""),
                "steps_count": len(info["steps"])
            }
            for name, info in all_workflows.items()
        },
        "nodes": list(all_nodes.keys()),
        "usage_examples": {
            "full_workflow": {
                "description": "Esegue il flusso completo di processing",
                "request": {
                    "workflow": "full",
                    "state": {"location": "...", "inbound": "...", "outbound": "..."}
                }
            },
            "email_only": {
                "description": "Invia solo email (richiede transcript esistente)",
                "request": {
                    "workflow": "email_only",
                    "state": {"conversation_id": "...", "scope": ["MAIL_PE"]}
                }
            },
            "custom_sequence": {
                "description": "Esegue una sequenza custom di nodi",
                "request": {
                    "workflow": ["reconstruct", "notify", "email"],
                    "state": {"location": "...", "inbound": "...", "outbound": "..."}
                }
            },
            "single_node": {
                "description": "Esegue un singolo nodo",
                "request": {
                    "workflow": "persist",
                    "state": {"conversation_id": "...", "transcript": "..."}
                }
            }
        }
    }

@api.get("/api/workflows/{workflow_name}")
async def get_workflow_details(workflow_name: str):
    """
    Ottieni dettagli di un workflow specifico.
    """
    workflow_info = workflow_registry.workflows.get(workflow_name)
    
    if not workflow_info:
        raise HTTPException(
            status_code=404, 
            detail=f"Workflow '{workflow_name}' non trovato"
        )
    
    return {
        "name": workflow_name,
        "steps": workflow_info["steps"],
        "description": workflow_info.get("description", ""),
        "steps_details": [
            {
                "order": i + 1,
                "node": step,
                "exists": workflow_registry.get_node(step) is not None
            }
            for i, step in enumerate(workflow_info["steps"])
        ]
    }

@api.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "config_loaded": config is not None,
        "nodes_count": len(workflow_registry.get_all_nodes()),
        "workflows_count": len(workflow_registry.get_all_workflows())
    }