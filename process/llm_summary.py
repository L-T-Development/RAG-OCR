import requests

OLLAMA_API = "http://localhost:11434/api/generate"
LLM_MODEL = "llama3.2"


def summarize_diff(diff_result: dict, timeout=30):
    """
    Generates a high-level, human-readable summary of document changes.
    Uses LLM ONLY for summarization (not detection).
    Safe to fail (returns None if LLM unavailable).
    """

    prompt = f"""
You are generating an executive-level document comparison summary.

STRICT RULES:
- Do NOT repeat raw diff text.
- Do NOT include symbols, bullets (•), or formatting artifacts.
- Do NOT mention words like OLD, NEW, REPLACED.
- Do NOT list every line change.
- Group changes by intent or topic.
- Keep language professional and concise.

INPUT DATA (ground truth, do not modify):
Added items:
{diff_result.get("added", [])}

Modified items:
{diff_result.get("modified", [])}

Removed items:
{diff_result.get("removed", [])}

REQUIRED OUTPUT FORMAT:

Added:
- High-level description of what was added

Modified:
- High-level description of what was changed

Removed:
- High-level description of what was removed

If a section has no meaningful changes, say "No significant changes".
Limit output to 6–10 bullet points total.
"""

    payload = {
        "model": LLM_MODEL,
        "prompt": prompt,
        "stream": False
    }

    try:
        res = requests.post(
            OLLAMA_API,
            json=payload,
            timeout=timeout
        )
        res.raise_for_status()
        data = res.json()
        return data.get("response", "").strip()

    except Exception:
        # LLM is optional → system must never fail
        return None
