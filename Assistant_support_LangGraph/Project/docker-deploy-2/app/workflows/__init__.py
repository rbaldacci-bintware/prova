# app/workflows/__init__.py
"""
Modulo workflows - Gestione workflow dinamici e multi-tenant.

Questo modulo permette di:
1. Registrare nuovi nodi personalizzati
2. Definire workflow predefiniti
3. Creare workflow custom al volo
4. Supportare multi-tenancy con workflow specifici per tenant
"""

from .registry import workflow_registry

__all__ = ['workflow_registry']