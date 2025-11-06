# app/graph_nodes.py - VERSIONE REFACTORED (NO URL HARDCODED)
import json
import logging
import asyncio
import aiofiles
from .state import GraphState
from .services import PersistenceClient, AudioTools
from .internal_api_client import InternalApiClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ RIMOSSO: Non più URL hardcoded qui
# Tutto gestito tramite InternalApiClient

# --- NODI ASYNC ---

async def conversation_reconstruction_node(state: GraphState) -> dict:
    """Nodo 1 ASYNC: Ricostruisce la conversazione da file audio"""
    print("--- NODO 1: RICOSTRUZIONE CONVERSAZIONE (ASYNC) ---")
    
    try:
        config = state.get("config", {})
        api_client = InternalApiClient(config)
        
        # Flusso principale: storage
        if state.get("location") and state.get("inbound") and state.get("outbound"):
            audio_tools = AudioTools(api_client)
            
            response = await audio_tools.reconstruct_from_storage(
                location=state["location"],
                inbound_filename=state["inbound"],
                outbound_filename=state["outbound"],
                project_name=state["project_name"]
            )
            
            # Marcatore async (usando metodo centralizzato)
            conversation_id = state.get("conversation_id")
            if conversation_id:
                await api_client.mark_stretch_completed(
                    conversation_id=conversation_id,
                    stretch_type="TRASCRIZIONE"
                )
            
            return {
                "transcript": response.reconstructedTranscript,
                "reconstruction": response.dict(),
                "tokens_used": response.usage.tokens,
                "cost_usd": response.usage.costUsd,
                "transcript_status": "CORRETTO"
            }
        
        # Flusso alternativo per test (file locali)
        elif len(state.get("audio_file_paths", [])) == 2:
            project_name = state.get("project_name")
            if not project_name:
                raise ValueError("project_name non trovato")
            
            params = {"project_name": project_name}
            files = []
            
            # Lettura file async
            for file_path in state["audio_file_paths"]:
                async with aiofiles.open(file_path, "rb") as f:
                    import os
                    ext = os.path.splitext(file_path)[1][1:]
                    mime_type = f"audio/{ext}"
                    file_content = await f.read()
                    files.append(('files', (os.path.basename(file_path), file_content, mime_type)))
            
            # ✅ USA URL CENTRALIZZATO
            url = f"{api_client.google_api_url}/api/Audio/reconstruct"
            
            import httpx
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(url, files=files, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                conversation_id = state.get("conversation_id")
                if conversation_id:
                    await api_client.mark_stretch_completed(
                        conversation_id=conversation_id,
                        stretch_type="TRASCRIZIONE"
                    )
                
                return {
                    "transcript": data["reconstructedTranscript"],
                    "reconstruction": data,
                    "tokens_used": data.get("usage", {}).get("tokens", 0),
                    "cost_usd": data.get("usage", {}).get("costUsd", 0.0),
                    "transcript_status": "CORRETTO"
                }
        
        raise ValueError("Input non valido per la ricostruzione.")
    
    except Exception as e:
        logger.error(f"❌ Errore durante trascrizione: {str(e)}")
        return {
            "transcript_status": "ERRORE",
            "transcript_error": str(e),
            "error": f"Errore trascrizione: {str(e)}"
        }


async def persistence_node(state: GraphState) -> dict:
    """Nodo 2 ASYNC: Salva la trascrizione nel database"""
    print("--- NODO 2: PERSISTENZA (ASYNC) ---")
    
    if not state.get("conversation_id"):
        logger.warning("conversation_id non presente, skip persistenza.")
        return {"persistence_result": "SKIPPED"}
    
    config = state.get("config", {})
    api_client = InternalApiClient(config)
    persistence_client = PersistenceClient(api_client)
    
    result = await persistence_client.save_conversation(
        conversation_id=state["conversation_id"],
        transcript=state["transcript"],
        type="TRASCRIZIONE"
    )
    
    logger.info(f"Persistenza: Status={result.status}, Id={result.id}")
    return {"persistence_result": f"{result.status}:{result.id}"}


async def email_node(state: GraphState) -> dict:
    """Nodo 3 ASYNC: Invia email tramite API esterna"""
    print("--- NODO 3: EMAIL (ASYNC) ---")
    
    scope = state.get("scope", [])
    if not scope:
        logger.info("Email non richiesta (scope vuoto)")
        return {"email_result": "SKIPPED_NO_SCOPE"}
    
    config = state.get("config", {})
    api_client = InternalApiClient(config)
    
    # Prepara scope
    scope_value = state.get("scope", [])
    if isinstance(scope_value, set):
        scope_value = list(scope_value)
    elif not isinstance(scope_value, list):
        scope_value = [scope_value] if scope_value else []
    
    # Serializza full_analysis
    full_analysis = state.get("full_analysis", {})
    analysis_json_string = json.dumps(full_analysis, ensure_ascii=False) if full_analysis else ""
    
    # Serializza output_mapping
    output_mapping_raw = state.get("output_mapping", {})
    
    if isinstance(output_mapping_raw, str):
        try:
            output_mapping_dict = json.loads(output_mapping_raw)
        except json.JSONDecodeError:
            output_mapping_dict = {}
    else:
        output_mapping_dict = output_mapping_raw
    
    if output_mapping_dict:
        ordered_mapping = {
            "report_type": output_mapping_dict.get("report_type"),
            "generator_class": output_mapping_dict.get("generator_class"),
            "output_mapping": output_mapping_dict.get("output_mapping")
        }
        output_mapping_json_string = json.dumps(ordered_mapping, ensure_ascii=False, separators=(',', ':'))
    else:
        output_mapping_json_string = ""
    
    # Payload
    graph_payload = {
        "request": {},
        "graph": {
            "edges": [],
            "nodes": [{
                "id": "email",
                "type": "tool",
                "plugin": "email",
                "function": "send_reconstruction_email",
                "outputKey": "emailResult",
                "parameters": {
                    "scope": "{{scope}}",
                    "co_code": "{{co_code}}",
                    "user_id": "{{user_id}}",
                    "caller_id": "{{caller_id}}",
                    "orgn_code": "{{orgn_code}}",
                    "conversationId": "{{conversationId}}",
                    "tenant_key": "{{tenant_key}}",
                    "id_assistito": "{{id_assistito}}",
                    "transcript": "{{transcript}}",
                    "structured_analysis": "{{structured_analysis}}",
                    "output_mapping": "{{output_mapping}}"
                }
            }],
            "startNodeId": "email"
        },
        "input": "",
        "state": {
            "scope": scope_value,
            "co_code": state.get("co_code", "none"),
            "user_id": state.get("user_id", "none"),
            "caller_id": state.get("caller_id", "none"),
            "orgn_code": state.get("orgn_code", "none"),
            "conversationId": state.get("conversation_id", "none"),
            "tenant_key": state.get("tenant_key", "none"),
            "id_assistito": state.get("id_assistito", "none"),
            "transcript": state.get("transcript", "none"),
            "structured_analysis": analysis_json_string,
            "output_mapping": output_mapping_json_string
        }
    }
    
    # ✅ USA METODO CENTRALIZZATO
    result = await api_client.send_email_via_graph(graph_payload)
    
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


async def analysis_node(state: GraphState) -> dict:
    """Nodo 4 ASYNC: Analizza la trascrizione con o senza Knowledge Base"""
    print("--- NODO 4: ANALISI AI (ASYNC) ---")

    try:
        transcript_content = state.get("transcript")
        if not transcript_content:
            raise ValueError("Trascrizione non presente")
        
        config = state.get("config", {})
        api_client = InternalApiClient(config)
        
        analysis_prompt = state.get("analysis_prompt")
        
        if not analysis_prompt:
            return {
                "error": "MISSING_ANALYSIS_PROMPT",
                "details": "Prompt obbligatorio non fornito",
                "analysis_status": "ERRORE"
            }
        
        if len(analysis_prompt.strip()) < 50:
            return {
                "error": "INVALID_ANALYSIS_PROMPT",
                "details": f"Prompt troppo corto ({len(analysis_prompt)} caratteri)",
                "analysis_status": "ERRORE"
            }
        
        knowledge_base_files_to_download = state.get("knowledge_base_files", [])
        
        if not knowledge_base_files_to_download:
            return {
                "error": "MISSING_KNOWLEDGE_BASE_FILES",
                "details": "knowledge_base_files è obbligatorio",
                "analysis_status": "ERRORE"
            }
        
        # Discriminante: verificare se location o fileName è "none"
        use_kb_analysis = True
        for file_info in knowledge_base_files_to_download:
            location = file_info.get("location")
            file_name = file_info.get("fileName")
            
            if location == "none" or file_name == "none":
                use_kb_analysis = False
                logger.info("⚠️ File con location o fileName = 'none' rilevato. Utilizzo analyze-transcript-only")
                break
        
        form_data = {
            'prompt': analysis_prompt,
            'projectName': state["project_name"],
            'geminiModelName': 'gemini-2.5-pro'
        }
        
        if use_kb_analysis:
            logger.info(f"📚 ANALISI CON KB ({len(knowledge_base_files_to_download)} file)")
            
            # ✅ Download parallelo usando metodo centralizzato
            download_tasks = [
                api_client.download_file(
                    file_info.get("location"),
                    file_info.get("fileName")
                )
                for file_info in knowledge_base_files_to_download
            ]
            
            downloaded_files_bytes = await asyncio.gather(*download_tasks)
            
            # Verifica downloads
            downloaded_files_content = []
            for i, file_bytes in enumerate(downloaded_files_bytes):
                if not file_bytes:
                    file_name = knowledge_base_files_to_download[i].get("fileName")
                    return {
                        "error": "DOWNLOAD_FAILED",
                        "failed_file": file_name,
                        "analysis_status": "ERRORE"
                    }
                file_name = knowledge_base_files_to_download[i].get("fileName")
                downloaded_files_content.append((file_name, file_bytes))
            
            logger.info(f"✅ KB files scaricati: {len(downloaded_files_content)}")
            
            # Prepara files
            files_to_upload = []
            for file_name, file_bytes in downloaded_files_content:
                files_to_upload.append(('ListaKnowledgeBase', (file_name, file_bytes, 'application/pdf')))
            files_to_upload.append(('TrascrizioneFile', ('trascrizione.txt', transcript_content.encode('utf-8'), 'text/plain')))
            
            # ✅ USA URL CENTRALIZZATO
            url = f"{api_client.google_api_url}/api/GeminiTextGeneration/analyze-file"
            
            import httpx
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(url, data=form_data, files=files_to_upload)
        else:
            logger.info("📄 ANALISI SOLO TRASCRIZIONE (KB file invalidi)")
            
            files_to_upload = [
                ('TrascrizioneFile', ('trascrizione.txt', transcript_content.encode('utf-8'), 'text/plain'))
            ]
            
            # ✅ USA URL CENTRALIZZATO
            url = f"{api_client.google_api_url}/api/GeminiTextGeneration/analyze-transcript-only"
            
            import httpx
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(url, data=form_data, files=files_to_upload)
        
        # Elaborazione risposta
        if response.status_code == 200:
            gemini_response = response.json()
            analysis_text = gemini_response['candidates'][0]['content']['parts'][0]['text']
            
            # Pulizia markdown
            if analysis_text.strip().startswith("```json"):
                analysis_text = analysis_text.strip()[7:-3]
            elif analysis_text.strip().startswith("```"):
                analysis_text = analysis_text.strip()[3:-3]

            analysis = json.loads(analysis_text)
            usage = gemini_response.get('usageMetadata', {})
            tokens_used = usage.get('totalTokenCount', 0)
            
            logger.info(f"✅ Analisi completata. Tokens: {tokens_used}")
            
            # Marcatore async (usando metodo centralizzato)
            conversation_id = state.get("conversation_id")
            if conversation_id:
                await api_client.mark_stretch_completed(
                    conversation_id=conversation_id,
                    stretch_type="ANALISI"
                )
            
            return {
                "full_analysis": analysis,
                "analysis_tokens_used": tokens_used,
                "analysis_status": "CORRETTO"
            }
        else:
            logger.error(f"❌ Errore API analisi: {response.status_code}")
            return {
                "error": f"API_ERROR_{response.status_code}",
                "analysis_status": "ERRORE"
            }

    except Exception as e:
        logger.error(f"❌ Eccezione analisi: {str(e)}")
        return {
            "error": "EXCEPTION",
            "details": str(e),
            "analysis_status": "ERRORE"
        }


async def suggestions_node(state: GraphState) -> dict:
    """Nodo 5 ASYNC: Estrae analisi e suggerimenti"""
    print("--- NODO 5: ESTRAZIONE DATI (ASYNC) ---")
    
    full_analysis = state.get("full_analysis", {})
    
    clusters = full_analysis.get("fase1_analisi_cluster", {})
    interaction = full_analysis.get("fase2_analisi_interazione", {})
    patterns = full_analysis.get("fase3_analisi_evento_critico", {})
    suggestions = full_analysis.get("fase4_suggerimenti_pedagogici", {})
    
    if not full_analysis:
        logger.warning("Nessuna analisi trovata")

    return {
        "cluster_analysis": clusters,
        "interaction_analysis": interaction,
        "patterns_insights": patterns,
        "suggestions": suggestions,
        "action_plan": suggestions.get("strategie_operative", [])
    }


async def save_analysis_node(state: GraphState) -> dict:
    """Nodo 6 ASYNC: Salva analisi e suggerimenti"""
    print("--- NODO 6: SALVATAGGIO ANALISI (ASYNC) ---")

    conversation_id = state.get("conversation_id")
    if not conversation_id:
        logger.warning("conversation_id non presente, skip salvataggio")
        return {"analysis_saved": False, "final_status": "SKIPPED"}

    clusters = state.get("cluster_analysis", {})
    interaction = state.get("interaction_analysis", {})
    patterns = state.get("patterns_insights", {})
    suggestions = state.get("suggestions", {})
    
    if not clusters and not interaction and not patterns:
        logger.warning("Dati analisi insufficienti")
        return {"analysis_saved": False, "final_status": "SKIPPED"}

    config = state.get("config", {})
    api_client = InternalApiClient(config)
    persistence_client = PersistenceClient(api_client)

    # Salvataggio parallelo async di ANALISI e SUGGERIMENTI
    analysis_payload = {
        "fase1_analisi_cluster": clusters,
        "fase2_analisi_interazione": interaction,
        "fase3_identificazione_pattern": patterns
    }
    analysis_json = json.dumps(analysis_payload, indent=2, ensure_ascii=False)
    
    suggestions_json = json.dumps(suggestions, indent=2, ensure_ascii=False) if suggestions else None
    
    # Salva in parallelo
    save_tasks = [
        persistence_client.save_conversation(conversation_id, analysis_json, "ANALISI")
    ]
    
    if suggestions_json:
        save_tasks.append(
            persistence_client.save_conversation(conversation_id, suggestions_json, "SUGGERIMENTI")
        )
    
    results = await asyncio.gather(*save_tasks)
    
    logger.info(f"Salvataggio ANALISI: Status={results[0].status}")
    if len(results) > 1:
        logger.info(f"Salvataggio SUGGERIMENTI: Status={results[1].status}")

    return {
        "analysis_saved": True,
        "final_status": "COMPLETED"
    }