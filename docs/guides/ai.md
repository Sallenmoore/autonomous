# AI adapters

Autonomous ships several AI-model backends — the ``BaseAgent``
provider strings ``local``, ``openai`` (HPC / OpenAI-compatible),
``gemini``, ``litellm``, ``flux`` (images) and ``mock`` — plus a generic
retry helper. This page covers ``local``, ``gemini`` and ``mock``.
Every backend implements the same ``generate_text`` / ``generate_json``
surface so you can swap between them without changing caller code.

## Install

```bash
pip install 'autonomous-app[ai]'   # google-genai + pydub for audio
```

The ``LocalAIModel`` and ``MockAIModel`` backends need only the core
``requests`` — they're in the base install.

## LocalAIModel

Talks to an [Ollama](https://ollama.com/) server at
``OLLAMA_API_BASE_URL`` (no default; set it).

```python
from autonomous.ai.models.local_model import LocalAIModel

ai = LocalAIModel()                      # model from $OLLAMA_MODEL
ai.generate_text("What's a queryset?", model="llama3.1")  # per-call override
ai.generate_json("Return a list of 3 planet names as JSON.",
                 context=[{"role": "user", "content": "..."}])
ai.summarize_text("... long article ...")
```

Media generation (image / audio / transcription) requires a
media-service endpoint set via env vars:

| Var | What it configures |
|-----|-------------------|
| ``OLLAMA_API_BASE_URL`` | Ollama base URL |
| ``MEDIA_API_BASE_URL`` | Media / embeddings service base URL |
| ``MEDIA_AUDIO_API_BASE_URL`` | Audio service base URL |
| ``MEDIA_IMAGE_API_BASE_URL`` | Image service base URL |

Each generation endpoint retries up to 3 times before giving up —
see ``autonomous.ai.retry`` below.

## GeminiAIModel

Uses Google's ``google-genai`` SDK:

```python
from autonomous.ai.models.gemini import GeminiAIModel

ai = GeminiAIModel()                 # reads $GOOGLEAI_KEY
ai.generate_text("...")
ai.generate_json("...")
ai.list_voices()
ai.generate_audio("...", voice_id="narrator")  # id hashed onto a preset voice
ai.generate_image("a cat wearing a hat")
```

Supports audio, image, and transcription.

## MockAIModel

Deterministic fake for tests. Never touches the network:

```python
from autonomous.ai.models.mock_model import MockAIModel

ai = MockAIModel()
ai.generate_text("anything")   # returns a canned mock response
```

Useful under ``pytest -m "not integration"``.

## Retry helper

``autonomous.ai.retry.retry`` is a tiny wrapper that runs a callable
up to N times with sleep between, optionally catching a specific
exception tuple, and optionally invoking an ``on_retry`` hook between
attempts:

```python
from autonomous.ai.retry import retry

def do_thing():
    ...

result = retry(
    do_thing,
    max_attempts=3,
    sleep_seconds=1.0,
    catch=(MyError,),
    on_retry=lambda attempt, exc: log(f"retry {attempt}: {exc}"),
    default=None,            # omit to re-raise on exhaustion
)
```

Used internally by ``LocalAIModel.generate_json`` (3 attempts, flushes
memory between them). Exposed publicly so your own adapters can
reuse the same pattern.

## Swapping backends

Every backend has the same public methods. A common pattern:

```python
if os.getenv("APP_ENV") == "test":
    ai = MockAIModel()
elif os.getenv("AI_BACKEND") == "gemini":
    ai = GeminiAIModel()
else:
    ai = LocalAIModel()
```

The caller code is agnostic:

```python
summary = ai.generate_text(f"Summarize: {article.body}")
```
