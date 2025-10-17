# app/graph.py - VERSIONE CON REGISTRY DINAMICO
import logging
from typing import Dict, Any, List, Optional
from langgraph.graph import StateGraph, END
from .state import GraphState

# Import del registry
from .workflows.registry import workflow_registry

# Import dei nodi base (esistenti)
from .graph_nodes import (
    conversation_reconstruction_node,
    persistence_node,
    email_node,
    analysis_node,
    suggestions_node,
    save_analysis_node
)

# Import dei nodi alternativi (nuovi)
from .workflows.email_only_nodes import WORKFLOW_NODES as EMAIL_WORKFLOW_NODES

logger = logging.getLogger(__name__)

# ===== REGISTRAZIONE NODI E WORKFLOW =====

def initialize_registry():
    """Inizializza il registry con tutti i nodi e workflow disponibili"""
    
    # 1. Registra NODI BASE (dal file graph_nodes.py originale)
    workflow_registry.register_nodes({
        "reconstruct": conversation_reconstruction_node,
        "persist": persistence_node,
        "email": email_node,
        "analyze": analysis_node,
        "suggest": suggestions_node,
        "save_analysis": save_analysis_node
    })
    
    # 2. Registra NODI WORKFLOW EMAIL (dal nuovo file)
    workflow_registry.register_nodes(EMAIL_WORKFLOW_NODES)
    
    # 3. Registra WORKFLOW PREDEFINITI
    workflow_registry.register_workflows({
        # Workflow completo COESO
        "full": ["reconstruct", "persist", "analyze", "suggest", "save_analysis", "email"],
        
        # Workflow rapidi
        "quick": ["reconstruct", "persist"],
        "transcribe_only": ["reconstruct"],
        
        # Workflow analisi
        "analysis_only": ["analyze", "suggest", "save_analysis"],
        "analysis_with_email": ["analyze", "suggest", "save_analysis", "email"],
        
        # Workflow email
        "email_only": ["email"],
        "resend_email": ["load_transcript", "quick_email"],
        
        # Workflow senza email
        "no_email": ["reconstruct", "persist", "analyze", "suggest", "save_analysis"],
        
        # Workflow notifiche
        "with_notification": ["reconstruct", "persist", "notify"],
        
        # Workflow custom
        "persist_and_email": ["persist", "email"],
        "analyze_and_notify": ["analyze", "notify"],

        # Workflow salva e invia trascrizione
        "save_and_email": ["persist", "email"],
        
        "transcribe_and_email": ["reconstruct", "email"],
        "transcribe_save_email": ["reconstruct", "persist", "email"],
    })
    
    logger.info(f"✅ Registry inizializzato con {len(workflow_registry.nodes)} nodi")
    logger.info(f"✅ Registry inizializzato con {len(workflow_registry.workflows)} workflow")

# Inizializza il registry
initialize_registry()

# ===== FUNZIONI DI ROUTING =====

def get_entry_point(state: GraphState) -> str:
    """Determina il punto di ingresso basato sullo state"""
    steps = state.get("steps", [])
    
    if not steps:
        logger.warning("Nessuno step definito")
        return END
    
    current_index = state.get("current_step_index", 0)
    if current_index < len(steps):
        return steps[current_index]
    
    return steps[0]

def route_to_next_step(state: GraphState) -> str:
    """Determina il prossimo nodo dopo l'esecuzione di uno step"""
    if state.get("skip_remaining"):
        logger.info("skip_remaining=True, termino il flusso")
        return END
    
    if state.get("error"):
        logger.error(f"Errore rilevato: {state['error']}, termino il flusso")
        return END
    
    steps = state.get("steps", [])
    current_index = state.get("current_step_index", 0)
    
    if current_index >= len(steps):
        logger.info(f"Completati tutti i {len(steps)} passi")
        return END
    
    next_node = steps[current_index]
    logger.info(f"Routing al prossimo nodo: {next_node} (step {current_index + 1}/{len(steps)})")
    return next_node

# ===== WRAPPER PER I NODI =====

def create_tracked_node(node_name: str, node_func):
    """Crea un wrapper che traccia l'esecuzione e gestisce gli errori"""
    def wrapped(state: GraphState) -> Dict[str, Any]:
        logger.info(f"🔷 Esecuzione nodo: {node_name}")
        trace = state.get("execution_trace", [])
        
        try:
            result = node_func(state)
            
            trace_copy = trace.copy()
            trace_copy.append(node_name)
            result["execution_trace"] = trace_copy
            
            current_index = state.get("current_step_index", 0)
            result["current_step_index"] = current_index + 1
            
            logger.info(f"✅ Nodo {node_name} completato con successo")
            return result
            
        except Exception as e:
            logger.error(f"❌ Errore nel nodo {node_name}: {str(e)}")
            
            trace_copy = trace.copy()
            trace_copy.append(f"{node_name}[ERROR]")
            
            return {
                "error": f"Errore in {node_name}: {str(e)}",
                "execution_trace": trace_copy,
                "skip_remaining": True,
                "current_step_index": state.get("current_step_index", 0) + 1
            }
    
    return wrapped

# ===== COSTRUZIONE DEL GRAFO =====

def build_dynamic_graph():
    """Costruisce il grafo dinamico universale usando il registry"""
    logger.info("🏗️ Costruzione del grafo dinamico da registry...")
    
    workflow = StateGraph(GraphState)
    
    # Ottieni tutti i nodi dal registry
    all_nodes = workflow_registry.get_all_nodes()
    
    # Aggiungi tutti i nodi disponibili con tracking
    for node_name, node_func in all_nodes.items():
        tracked_func = create_tracked_node(node_name, node_func)
        workflow.add_node(node_name, tracked_func)
        logger.info(f"  ✓ Aggiunto nodo: {node_name}")
    
    # Entry point condizionale
    workflow.add_conditional_edges(
        "__start__",
        get_entry_point,
        {node: node for node in all_nodes.keys()}
    )
    
    # Ogni nodo decide dove andare dopo
    for node_name in all_nodes.keys():
        workflow.add_conditional_edges(
            node_name,
            route_to_next_step,
            {
                **{other_node: other_node for other_node in all_nodes.keys()},
                END: END
            }
        )
    
    compiled = workflow.compile()
    logger.info("✅ Grafo dinamico compilato con successo!")
    return compiled

# ===== HELPER FUNCTIONS =====

def prepare_workflow_steps(workflow_request: Optional[str | List[str]]) -> List[str]:
    """
    Prepara la lista di steps basata sulla richiesta.
    
    Args:
        workflow_request: Può essere:
            - None/vuoto -> workflow "full"
            - string -> nome di un workflow preset
            - List[str] -> lista custom di nodi
    """
    if not workflow_request:
        # Default: workflow completo
        return workflow_registry.get_workflow_steps("full")
    
    if isinstance(workflow_request, str):
        # È un workflow preset?
        preset_steps = workflow_registry.get_workflow_steps(workflow_request)
        if preset_steps:
            return preset_steps
        
        # Altrimenti interpretalo come singolo nodo
        if workflow_registry.get_node(workflow_request):
            return [workflow_request]
        
        logger.warning(f"⚠️ Workflow/nodo '{workflow_request}' non trovato, uso 'full'")
        return workflow_registry.get_workflow_steps("full")
    
    if isinstance(workflow_request, list):
        # Valida che tutti i nodi esistano
        valid_steps = []
        for step in workflow_request:
            if workflow_registry.get_node(step):
                valid_steps.append(step)
            else:
                logger.warning(f"⚠️ Nodo '{step}' non esiste, verrà ignorato")
        
        if not valid_steps:
            logger.error("Nessun nodo valido nella lista custom, uso workflow 'full'")
            return workflow_registry.get_workflow_steps("full")
        
        return valid_steps
    
    return workflow_registry.get_workflow_steps("full")

# ===== ESPORTA IL GRAFO =====

# Grafo dinamico principale
dynamic_graph = build_dynamic_graph()

# Per retrocompatibilità
conversation_graph = dynamic_graph
complete_graph = dynamic_graph

print("✅ Sistema di routing dinamico con registry pronto!")
print(f"   Nodi disponibili: {list(workflow_registry.get_all_nodes().keys())}")
print(f"   Workflow predefiniti: {list(workflow_registry.get_all_workflows().keys())}")