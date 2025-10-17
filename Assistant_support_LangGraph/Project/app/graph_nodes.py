# app/graph_nodes.py
import os
import json
import logging
import requests
from .state import GraphState
from .services import PersistenceClient, AudioTools
from .internal_api_client import InternalApiClient

# Configurazione logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# URL delle API (lette da variabili d'ambiente, con fallback)
API_URL = os.getenv("GOOGLE_API_URL", "http://localhost:5020")
FILE_API_URL = os.getenv("FileApiBaseUrl", "http://localhost:5019")

# --- FUNZIONE HELPER PER MARCATORE ---

def mark_stretch_completed(conversation_id: str, api_key: str, base_url: str, stretch_type: str) -> bool:
    """
    Marca uno stretch come completato chiamando l'API C#.
    
    Args:
        conversation_id: ID della conversazione
        api_key: Chiave API per autenticazione
        base_url: URL base dell'API (es. http://localhost:5010)
        stretch_type: Tipo di stretch ("TRASCRIZIONE" o "ANALISI") - solo per logging
    
    Returns:
        True se il marcatore è stato inserito con successo, False altrimenti
    """
    if not conversation_id:
        logger.warning(f"[{stretch_type}] conversation_id mancante, skip marcatore")
        return False
    
    url = f"{base_url}/api/InternalConversazione/UpdateConversazioneStretchCompleted"
    params = {"convName": conversation_id,
              "ind_type": stretch_type}
    headers = {"X-Api-Key": api_key}
    
    try:
        logger.info(f"[{stretch_type}] Inserimento marcatore per conversazione: {conversation_id}")
        response = requests.put(url, params=params, headers=headers, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"✅ [{stretch_type}] Marcatore inserito con successo")
            return True
        elif response.status_code == 404:
            logger.error(f"❌ [{stretch_type}] Conversazione {conversation_id} non trovata (404)")
            return False
        else:
            logger.error(f"❌ [{stretch_type}] Errore inserimento marcatore: {response.status_code} - {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        logger.error(f"⏱️ [{stretch_type}] Timeout durante inserimento marcatore")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ [{stretch_type}] Errore di rete durante inserimento marcatore: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"❌ [{stretch_type}] Errore generico durante inserimento marcatore: {str(e)}")
        return False

# --- NODI DEL GRAFO ---

def conversation_reconstruction_node(state: GraphState) -> dict:
    """Nodo 1: Ricostruisce la conversazione da file audio."""
    print("--- NODO 1: RICOSTRUZIONE CONVERSAZIONE ---")
    
    try:
        # Flusso principale: usa i riferimenti ai file audio nello storage
        if state.get("location") and state.get("inbound") and state.get("outbound"):
            config = state.get("config", {})
            api_client = InternalApiClient(config)
            audio_tools = AudioTools(api_client)
            
            response = audio_tools.reconstruct_from_storage(
                location=state["location"],
                inbound_filename=state["inbound"],
                outbound_filename=state["outbound"],
                project_name=state["project_name"]
            )
            
            # 🆕 INSERIMENTO MARCATORE SE TRASCRIZIONE RIUSCITA
            conversation_id = state.get("conversation_id")
            if conversation_id:
                mark_stretch_completed(
                    conversation_id=conversation_id,
                    api_key=api_client.api_key,
                    base_url=api_client.base_url,
                    stretch_type="TRASCRIZIONE"
                )
            
            return {
                "transcript": response.reconstructedTranscript,
                "reconstruction": response.dict(),
                "tokens_used": response.usage.tokens,
                "cost_usd": response.usage.costUsd,
                "transcript_status": "CORRETTO"  # Marcatore locale
            }
        
        # Flusso alternativo per test: usa percorsi di file locali
        elif len(state.get("audio_file_paths", [])) == 2:
            project_name = state.get("project_name")
            if not project_name:
                raise ValueError("project_name non trovato")
            
            params = {"project_name": project_name}
            files = []
            for file_path in state["audio_file_paths"]:
                with open(file_path, "rb") as f:
                    ext = os.path.splitext(file_path)[1][1:]
                    mime_type = f"audio/{ext}"
                    file_content = f.read()
                    files.append(('files', (os.path.basename(file_path), file_content, mime_type)))
            
            response = requests.post(f"{API_URL}/api/Audio/reconstruct", files=files, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                # 🆕 INSERIMENTO MARCATORE SE TRASCRIZIONE RIUSCITA
                conversation_id = state.get("conversation_id")
                if conversation_id:
                    config = state.get("config", {})
                    if config:
                        api_client = InternalApiClient(config)
                        mark_stretch_completed(
                            conversation_id=conversation_id,
                            api_key=api_client.api_key,
                            base_url=api_client.base_url,
                            stretch_type="TRASCRIZIONE"
                        )
                
                return {
                    "transcript": data["reconstructedTranscript"],
                    "reconstruction": data,
                    "tokens_used": data.get("usage", {}).get("tokens", 0),
                    "cost_usd": data.get("usage", {}).get("costUsd", 0.0),
                    "transcript_status": "CORRETTO"
                }
        
        raise ValueError("Input non valido per la ricostruzione. Fornire 'location'/'inbound'/'outbound' o 'audio_file_paths'.")
    
    except Exception as e:
        logger.error(f"❌ Errore durante trascrizione: {str(e)}")
        return {
            "transcript_status": "ERRORE",
            "transcript_error": str(e),
            "error": f"Errore trascrizione: {str(e)}"
        }

def persistence_node(state: GraphState) -> dict:
    """Nodo 2: Salva la trascrizione nel database."""
    print("--- NODO 2: PERSISTENZA ---")
    
    if not state.get("conversation_id"):
        logger.warning("conversation_id non presente, skip persistenza.")
        return {"persistence_result": "SKIPPED"}
    
    config = state.get("config", {})
    api_client = InternalApiClient(config)
    persistence_client = PersistenceClient(api_client)
    
    result = persistence_client.save_conversation(
        conversation_id=state["conversation_id"],
        transcript=state["transcript"],
        type="TRASCRIZIONE"
    )
    
    logger.info(f"Persistenza: Status={result.status}, Id={result.id}")
    return {"persistence_result": f"{result.status}:{result.id}"}


def email_node(state: GraphState) -> dict:
    """Nodo 3: Invia email tramite API esterna."""
    print("--- NODO 3: EMAIL ---")
    
    # Controlla se l'invio email è richiesto
    scope = state.get("scope", [])
    if not scope:
        logger.info("Email non richiesta (scope vuoto)")
        return {"email_result": "SKIPPED_NO_SCOPE"}
    
    # Ottieni la configurazione
    config = state.get("config", {})
    api_client = InternalApiClient(config)
    api_key = api_client.api_key
    
    # URL dell'API Email
    #EMAIL_API_URL = os.getenv("EMAIL_API_URL", "http://localhost:5007")
    EMAIL_API_URL = os.getenv("EMAIL_API_URL", "http://192.168.1.28:5007")
    # Prepara lo scope convertendolo sempre in lista
    scope_value = state.get("scope", [])
    if isinstance(scope_value, set):
        scope_value = list(scope_value)
    elif not isinstance(scope_value, list):
        scope_value = [scope_value] if scope_value else []
    
    # Serializza full_analysis
    full_analysis = state.get("full_analysis", {})
    analysis_json_string = json.dumps(full_analysis, ensure_ascii=False) if full_analysis else ""
    
   
   # Serializza output_mapping con ORDINE CORRETTO
    output_mapping_raw = state.get("output_mapping", {})
    
    logger.info(f"OUTPUT_MAPPING tipo: {type(output_mapping_raw)}")
    
    # ✅ SEMPRE parsare e ricostruire per garantire formato corretto
    if isinstance(output_mapping_raw, str):
        # Parse la stringa JSON
        try:
            output_mapping_dict = json.loads(output_mapping_raw)
            logger.info("OUTPUT_MAPPING parsato da stringa JSON")
        except json.JSONDecodeError:
            logger.error("Errore nel parse di output_mapping, uso dict vuoto")
            output_mapping_dict = {}
    else:
        # È già un dict
        output_mapping_dict = output_mapping_raw
        logger.info("OUTPUT_MAPPING già in formato dict")
    
    # Ricostruisci SEMPRE con l'ordine corretto
    if output_mapping_dict:
        ordered_mapping = {
            "report_type": output_mapping_dict.get("report_type"),
            "generator_class": output_mapping_dict.get("generator_class"),
            "output_mapping": output_mapping_dict.get("output_mapping")
        }
        output_mapping_json_string = json.dumps(ordered_mapping, ensure_ascii=False, separators=(',', ':'))

        
        # 🔍 PRINT COMPLETO - RIMUOVI IL TRONCAMENTO
        logger.info("=" * 80)
        logger.info("OUTPUT_MAPPING JSON COMPLETO:")
        logger.info(output_mapping_json_string)  # ← Senza [:200]
        logger.info("=" * 80)
    else:
        output_mapping_json_string = ""
        logger.info("OUTPUT_MAPPING vuoto")

    # Costruisci il payload nel formato richiesto
    graph_payload = {
        "request": {},
        "graph": {
            "edges": [],
            "nodes": [
                {
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
                }
            ],
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
    
    logger.info("=" * 80)
    logger.info("OUTPUT_MAPPING CHE VERRÀ INVIATO:")
    logger.info(graph_payload["state"]["output_mapping"])
    logger.info("=" * 80)

    # Headers per la richiesta
    headers = {
        'accept': 'text/plain',
        'X-Api-Key': api_key,
        'Content-Type': 'application/json'
    }
    
    try:
        logger.info(f"Invio email tramite API: {EMAIL_API_URL}/api/Graph/run")
        logger.debug(f"Email payload scope: {scope_value}")
        
        response = requests.post(
            f"{EMAIL_API_URL}/api/Graph/run",
            json=graph_payload,
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            logger.info("✅ Email inviata con successo")
            return {
                "email_result": "SUCCESS",
                "email_response": response.text
            }
        else:
            logger.error(f"❌ Errore invio email: Status={response.status_code}, Body={response.text}")
            return {
                "email_result": f"ERROR_{response.status_code}",
                "email_error": response.text
            }
            
    except requests.exceptions.Timeout:
        logger.error("⏱️ Timeout durante l'invio dell'email")
        return {"email_result": "TIMEOUT"}
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Errore di rete durante l'invio email: {str(e)}")
        return {"email_result": "NETWORK_ERROR", "email_error": str(e)}
    except Exception as e:
        logger.error(f"❌ Errore generico durante l'invio email: {str(e)}")
        return {"email_result": "ERROR", "email_error": str(e)}

def _download_file(location: str, file_name: str, api_key: str) -> bytes:
    """Funzione helper per scaricare un file come array di byte."""
    url = f"{FILE_API_URL}/api/files/{location}/{file_name}"
    headers = {'Accept': 'application/octet-stream', 'X-Api-Key': api_key}
    try:
        logger.info(f"Download knowledge base file da: {url}")
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        return response.content
    except requests.exceptions.RequestException as e:
        logger.error(f"Errore durante il download del file {file_name}: {e}")
        return None


def analysis_node(state: GraphState) -> dict:
    """Nodo 4: Analizza la trascrizione con o senza Knowledge Base."""
    print("--- NODO 4: ANALISI AI ---")

    try:
        transcript_content = state.get("transcript")
        if not transcript_content:
            raise ValueError("La trascrizione non è presente nello stato e non può essere analizzata.")
        
        config = state.get("config", {})
        api_client = InternalApiClient(config)
        internal_api_key = api_client.api_key
        
        # 🚨 PROMPT OBBLIGATORIO
        analysis_prompt = state.get("analysis_prompt")
        
        if not analysis_prompt:
            error_msg = "❌ ERRORE: 'analysis_prompt' è obbligatorio per l'analisi ma non è stato fornito nello state."
            logger.error(error_msg)
            return {
                "error": "MISSING_ANALYSIS_PROMPT",
                "details": error_msg,
                "final_status": "ERROR",
                "analysis_status": "ERRORE"
            }
        
        # Validazione lunghezza minima
        if len(analysis_prompt.strip()) < 50:
            error_msg = f"❌ ERRORE: Il prompt fornito è troppo corto ({len(analysis_prompt)} caratteri). Minimo richiesto: 50 caratteri."
            logger.error(error_msg)
            return {
                "error": "INVALID_ANALYSIS_PROMPT",
                "details": error_msg,
                "final_status": "ERROR",
                "analysis_status": "ERRORE"
            }
        
        logger.info(f"✅ Utilizzo prompt fornito ({len(analysis_prompt)} caratteri)")
        
        # ========================================================================
        # 🔀 DECISIONE: Con o senza Knowledge Base
        # ========================================================================
        knowledge_base_files_to_download = state.get("knowledge_base_files", [])
        
        # Preparazione form data (comune)
        form_data = {
            'prompt': analysis_prompt,
            'projectName': state["project_name"],
            'geminiModelName': 'gemini-2.5-pro'
        }
        
        if knowledge_base_files_to_download:
            # ============================================================
            # PERCORSO 1: CON KNOWLEDGE BASE
            # ============================================================
            logger.info(f"📚 Modalità: ANALISI CON KNOWLEDGE BASE ({len(knowledge_base_files_to_download)} file)")
            
            # Download dei file KB
            downloaded_files_content = []
            for file_info in knowledge_base_files_to_download:
                location = file_info.get("location")
                file_name = file_info.get("fileName")
                
                if not location or not file_name:
                    error_msg = f"File info incompleto: {file_info}. Richiesti 'location' e 'fileName'"
                    logger.error(error_msg)
                    return {
                        "error": "INVALID_FILE_INFO",
                        "details": error_msg,
                        "final_status": "ERROR",
                        "analysis_status": "ERRORE"
                    }
                    
                logger.info(f"Download file KB: {file_name} da location: {location}")
                file_bytes = _download_file(location, file_name, internal_api_key)
                
                if not file_bytes:
                    error_msg = f"Impossibile scaricare il file di knowledge base: {file_name} da {location}"
                    logger.error(error_msg)
                    return {
                        "error": "DOWNLOAD_FAILED",
                        "details": error_msg,
                        "failed_file": file_name,
                        "final_status": "ERROR",
                        "analysis_status": "ERRORE"
                    }
                
                downloaded_files_content.append((file_name, file_bytes))

            logger.info(f"✅ Scaricati con successo {len(downloaded_files_content)} file KB")

            # Upload dei file (KB + trascrizione)
            files_to_upload = []
            for file_name, file_bytes in downloaded_files_content:
                files_to_upload.append(('ListaKnowledgeBase', (file_name, file_bytes, 'application/pdf')))
            files_to_upload.append(('TrascrizioneFile', ('trascrizione.txt', transcript_content.encode('utf-8'), 'text/plain')))

            # Chiamata API con KB
            response = requests.post(
                f"{API_URL}/api/GeminiTextGeneration/analyze-file",
                data=form_data,
                files=files_to_upload,
                timeout=180
            )
            
        else:
            # ============================================================
            # PERCORSO 2: SENZA KNOWLEDGE BASE (solo trascrizione)
            # ============================================================
            logger.info("📄 Modalità: ANALISI SOLO TRASCRIZIONE (nessuna KB)")
            
            # Upload SOLO della trascrizione
            files_to_upload = [
                ('TrascrizioneFile', ('trascrizione.txt', transcript_content.encode('utf-8'), 'text/plain'))
            ]

            # Chiamata API senza KB
            response = requests.post(
                f"{API_URL}/api/GeminiTextGeneration/analyze-transcript-only",
                data=form_data,
                files=files_to_upload,
                timeout=180
            )

        # ========================================================================
        # ELABORAZIONE RISPOSTA (comune per entrambi i percorsi)
        # ========================================================================
        if response.status_code == 200:
            gemini_response = response.json()
            analysis_text = gemini_response['candidates'][0]['content']['parts'][0]['text']
            
            # Pulizia markdown se presente
            if analysis_text.strip().startswith("```json"):
                analysis_text = analysis_text.strip()[7:-3]
            elif analysis_text.strip().startswith("```"):
                analysis_text = analysis_text.strip()[3:-3]

            analysis = json.loads(analysis_text)
            
            usage = gemini_response.get('usageMetadata', {})
            tokens_used = usage.get('totalTokenCount', 0)
            
            logger.info(f"✅ Analisi completata con successo. Tokens usati: {tokens_used}")
            
            # 🆕 INSERIMENTO MARCATORE SE ANALISI RIUSCITA
            conversation_id = state.get("conversation_id")
            if conversation_id:
                mark_stretch_completed(
                    conversation_id=conversation_id,
                    api_key=internal_api_key,
                    base_url=api_client.base_url,
                    stretch_type="ANALISI"
                )
            
            return {
                "full_analysis": analysis,
                "analysis_tokens_used": tokens_used,
                "analysis_status": "CORRETTO"
            }
        else:
            logger.error(f"❌ Errore API analisi: Status {response.status_code}, Dettagli: {response.text}")
            return {
                "error": f"API_ERROR_{response.status_code}",
                "details": response.text,
                "final_status": "ERROR",
                "analysis_status": "ERRORE"
            }

    except Exception as e:
        logger.error(f"❌ Eccezione durante la chiamata di analisi: {str(e)}")
        return {
            "error": "EXCEPTION",
            "details": str(e),
            "final_status": "ERROR",
            "analysis_status": "ERRORE"
        }


def suggestions_node(state: GraphState) -> dict:
    """Nodo 5: Estrae l'analisi e i suggerimenti dallo stato."""
    print("--- NODO 5: ESTRAZIONE DATI DI ANALISI ---")
    
    full_analysis = state.get("full_analysis", {})
    
    clusters = full_analysis.get("fase1_analisi_cluster", {})
    interaction = full_analysis.get("fase2_analisi_interazione", {})
    patterns = full_analysis.get("fase3_analisi_evento_critico", {})
    suggestions = full_analysis.get("fase4_suggerimenti_pedagogici", {})
    
    if not full_analysis:
        logger.warning("Nessuna analisi completa trovata nello stato.")

    return {
        "cluster_analysis": clusters,
        "interaction_analysis": interaction,
        "patterns_insights": patterns,
        "suggestions": suggestions,
        "action_plan": suggestions.get("strategie_operative", [])
    }
    

def save_analysis_node(state: GraphState) -> dict:
    """Nodo 6: Salva l'analisi e i suggerimenti in due record separati."""
    print("--- NODO 6: SALVATAGGIO ANALISI E SUGGERIMENTI ---")

    conversation_id = state.get("conversation_id")
    if not conversation_id:
        logger.warning("conversation_id non presente, skip salvataggio.")
        return {"analysis_saved": False, "final_status": "SKIPPED"}

    # MODIFICA CHIAVE: Estrae i dati corretti dallo stato
    clusters = state.get("cluster_analysis", {})
    interaction = state.get("interaction_analysis", {})
    patterns = state.get("patterns_insights", {})
    suggestions = state.get("suggestions", {})
    
    if not clusters and not interaction and not patterns:
        logger.warning("Dati di analisi non sufficienti per il salvataggio.")
        return {"analysis_saved": False, "final_status": "SKIPPED"}

    config = state.get("config", {})
    api_client = InternalApiClient(config)
    persistence_client = PersistenceClient(api_client)

    # 1. Prepara e salva il blocco di ANALISI (Fasi 1-3)
    analysis_payload = {
        "fase1_analisi_cluster": clusters,
        "fase2_analisi_interazione": interaction,
        "fase3_identificazione_pattern": patterns
    }
    analysis_json_string = json.dumps(analysis_payload, indent=2, ensure_ascii=False)
    result_analysis = persistence_client.save_conversation(
        conversation_id=conversation_id,
        transcript=analysis_json_string,
        type="ANALISI"
    )
    logger.info(f"Salvataggio ANALISI: Status={result_analysis.status}, Id={result_analysis.id}")
    
    # 2. Prepara e salva il blocco dei SUGGERIMENTI (Fase 4)
    if suggestions:
        suggestions_json_string = json.dumps(suggestions, indent=2, ensure_ascii=False)
        result_suggestions = persistence_client.save_conversation(
            conversation_id=conversation_id,
            transcript=suggestions_json_string,
            type="SUGGERIMENTI"
        )
        logger.info(f"Salvataggio SUGGERIMENTI: Status={result_suggestions.status}, Id={result_suggestions.id}")

    return {
        "analysis_saved": True,
        "final_status": "COMPLETED"
    }