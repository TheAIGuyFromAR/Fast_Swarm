"""
LLM Service for Fast_Swarm.

Provides async LLM calls via Ollama for:
- Agent pattern selection (birth_selection.j2)
- Philosophy generation (philosophy.j2)
- AI zone decisions (ai_zone_decision.j2)

Uses the centralized Ollama configuration from Fast_Swarm.local_agents.config.
"""

import asyncio
import logging

import httpx

# time.sleep used in sync retry
import time as _time

logger = logging.getLogger(__name__)

# Ollama config (mirrors local_agents/config.py)
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "koshtenco/agi-trader-kz50-quantum:latest"
OLLAMA_TIMEOUT = 30  # seconds
MAX_RETRIES = 3


async def ollama_call_async(prompt: str) -> str:
    """
    Call Ollama API asynchronously with retry and exponential backoff.

    Retries up to MAX_RETRIES times on timeout or connection errors.
    This prevents a single Ollama hiccup from crashing the evolution cycle.

    Args:
        prompt: The prompt to send to the LLM.

    Returns:
        The LLM response text.

    Raises:
        RuntimeError: If Ollama is unavailable after all retries.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_gpu": 99,  # Use all GPU layers
            "num_ctx": 512,  # Minimal context for speed
            "num_predict": 200,  # Allow slightly longer responses for JSON
            "temperature": 0.1,  # Consistent decisions
        },
    }

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
                response = await client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
                return result.get("response", "")
        except httpx.TimeoutException as e:
            last_error = e
            backoff = 2 ** attempt
            logger.warning(
                "[LLMService] Ollama timeout (attempt %d/%d), retrying in %ds...",
                attempt + 1, MAX_RETRIES, backoff,
            )
            await asyncio.sleep(backoff)
        except httpx.ConnectError as e:
            last_error = e
            backoff = 2 ** attempt
            logger.warning(
                "[LLMService] Ollama connection failed (attempt %d/%d), retrying in %ds...",
                attempt + 1, MAX_RETRIES, backoff,
            )
            await asyncio.sleep(backoff)
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"[LLMService] Ollama HTTP error: {e.response.status_code}")

    raise RuntimeError(
        f"[LLMService] Ollama unavailable after {MAX_RETRIES} retries: {last_error}"
    )


def ollama_call_sync(prompt: str) -> str:
    """
    Synchronous Ollama call with retry and exponential backoff.

    Used by genesis.py which expects a sync function.
    Uses synchronous httpx to avoid asyncio issues in thread pools.

    Args:
        prompt: The prompt to send to the LLM.

    Returns:
        The LLM response text.

    Raises:
        RuntimeError: If Ollama is unavailable after all retries.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_gpu": 99,
            "num_ctx": 2048,  # Larger context for pattern list
            "num_predict": 500,  # Allow longer JSON responses
            "temperature": 0.1,
        },
    }

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            with httpx.Client(timeout=OLLAMA_TIMEOUT) as client:
                logger.info("[LLMService] Calling Ollama with %d char prompt...", len(prompt))
                response = client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
                llm_response = result.get("response", "")
                logger.info("[LLMService] Got %d char response from Ollama", len(llm_response))
                return llm_response
        except httpx.TimeoutException as e:
            last_error = e
            backoff = 2 ** attempt
            logger.warning(
                "[LLMService] Ollama timeout (attempt %d/%d), retrying in %ds...",
                attempt + 1, MAX_RETRIES, backoff,
            )
            _time.sleep(backoff)
        except httpx.ConnectError as e:
            last_error = e
            backoff = 2 ** attempt
            logger.warning(
                "[LLMService] Ollama connection failed (attempt %d/%d), retrying in %ds...",
                attempt + 1, MAX_RETRIES, backoff,
            )
            _time.sleep(backoff)
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"[LLMService] Ollama HTTP error: {e.response.status_code}")

    raise RuntimeError(
        f"[LLMService] Ollama unavailable after {MAX_RETRIES} retries: {last_error}"
    )


async def check_ollama_available() -> bool:
    """Check if Ollama is running and the model is loaded."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m.get("name", "") for m in models]
                return OLLAMA_MODEL in model_names or any(OLLAMA_MODEL.split(":")[0] in name for name in model_names)
        return False
    except Exception:
        return False
