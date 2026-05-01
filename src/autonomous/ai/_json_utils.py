"""
Shared utilities for cleaning JSON responses from LLMs that don't reliably
honor structured-output requests (Llama 3 / Gemma family in particular, but
also OpenAI-compatible endpoints when `response_format=json_object` is
ignored by the served model).
"""

import re


def clean_json_response(text):
    """
    Robust cleaner for LLM JSON outputs.

    Handles markdown code blocks, prose chatter before/after the JSON object,
    and the case where the model returns naked field-pairs without a wrapping
    `{ }`.

    Returns a string that is expected to be valid JSON; the caller is still
    responsible for `json.loads(...)`.
    """
    text = text.strip()

    # 1. Strip markdown code blocks (```json ... ``` or ``` ... ```).
    if "```" in text:
        pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            text = match.group(1)
        else:
            # Fallback: take everything between the first and last triple-tick.
            start = text.find("```")
            end = text.rfind("```")
            first_newline = text.find("\n", start)
            if first_newline != -1 and first_newline < end:
                text = text[first_newline:end]

    # 2. Heuristic: extract from the first '{' to the last '}'.
    # Fixes "Here is the JSON: { ... }" and similar prose-prefixed responses.
    start_idx = text.find("{")
    end_idx = text.rfind("}")

    if start_idx != -1 and end_idx != -1:
        text = text[start_idx : end_idx + 1]
    elif text.strip() and '":' in text:
        # Naked field-pairs: '"name": "Aria", "desc": "..."' -> wrap in '{ }'.
        # Gated on `":"` so prose error strings ("I couldn't generate that.")
        # without JSON structure aren't wrapped.
        stripped = text.strip().rstrip(",")
        text = "{" + stripped + "}"

    return text.strip()
