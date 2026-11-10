"""Check which Vertex AI locations serve the configured Gemini model."""
from google import genai

from pipeline import config

for location in ("europe-west2", "global"):
    try:
        client = genai.Client(
            vertexai=True, project=config.PROJECT_ID, location=location
        )
        resp = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents="Reply with the single word: ready",
        )
        usage = resp.usage_metadata
        print(f"{location}: OK -> {resp.text.strip()!r} "
              f"(in={usage.prompt_token_count}, out={usage.candidates_token_count})")
    except Exception as exc:
        print(f"{location}: FAILED -> {type(exc).__name__}: {str(exc)[:200]}")
