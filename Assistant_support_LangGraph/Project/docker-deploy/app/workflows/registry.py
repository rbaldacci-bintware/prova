# app/workflows/registry.py
from typing import Dict, List, Callable, Optional
import logging

logger = logging.getLogger(__name__)

class WorkflowRegistry:
    """
    Registry centralizzato per gestire workflow multipli e multi-tenant.
    Permette di registrare nodi e workflow dinamicamente.
    """
    
    def __init__(self):
        self.workflows: Dict[str, Dict] = {}
        self.nodes: Dict[str, Callable] = {}
        
    def register_node(self, name: str, function: Callable):
        """Registra un singolo nodo"""
        self.nodes[name] = function
        logger.info(f"✓ Nodo registrato: {name}")
    
    def register_nodes(self, nodes_dict: Dict[str, Callable]):
        """Registra multipli nodi da un dizionario"""
        for name, func in nodes_dict.items():
            self.register_node(name, func)
    
    def register_workflow(self, name: str, steps: List[str], description: str = ""):
        """Registra un workflow predefinito"""
        self.workflows[name] = {
            "steps": steps,
            "description": description
        }
        logger.info(f"✓ Workflow registrato: {name} - {len(steps)} passi")
    
    def register_workflows(self, workflows_dict: Dict[str, List[str]]):
        """Registra multipli workflow da un dizionario"""
        for name, steps in workflows_dict.items():
            self.register_workflow(name, steps)
    
    def get_workflow_steps(self, workflow_name: str) -> List[str]:
        """Ottieni i passi di un workflow per nome"""
        if workflow_name in self.workflows:
            return self.workflows[workflow_name]["steps"]
        return None
    
    def get_node(self, node_name: str) -> Optional[Callable]:
        """Ottieni un nodo per nome"""
        return self.nodes.get(node_name)
    
    def get_all_nodes(self) -> Dict[str, Callable]:
        """Ottieni tutti i nodi registrati"""
        return self.nodes
    
    def get_all_workflows(self) -> Dict[str, Dict]:
        """Ottieni tutti i workflow registrati"""
        return self.workflows
    
    def validate_workflow(self, steps: List[str]) -> bool:
        """Valida che tutti i nodi di un workflow esistano"""
        for step in steps:
            if step not in self.nodes:
                logger.error(f"❌ Nodo '{step}' non esiste nel registry")
                return False
        return True

# Istanza globale del registry
workflow_registry = WorkflowRegistry()