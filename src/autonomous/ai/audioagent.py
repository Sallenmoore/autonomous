from autonomous import log
from autonomous.ai.baseagent import BaseAgent
from autonomous.model.autoattr import StringAttr
from autonomous.ai._credentials import client_key_scope
from autonomous.ai._routing import resolve_client


# LLM dramatize prompt — applied once over the COMPLETE transcript, not
# interleaved per-chunk. The previous design threaded a 1000-char rolling
# context between chunks; with full-transcript input that crutch is no
# longer needed.
DRAMATIZE_PROMPT = """\
You are an expert TTRPG Scribe. Rewrite the following raw, automated
audio transcript into a clean, readable screenplay format.

GUIDELINES:
1. Identify speakers using the World Context (player roster, NPC names).
   When a speaker can't be confidently identified, label them
   "UNKNOWN [Number]" and stay consistent for that voice.
2. Remove verbal tics ("um", "uh") and off-topic table cross-talk
   (e.g., passing snacks).
3. KEEP EVERY RELEVANT SPOKEN WORD. Do not summarize the story.
4. Output ONLY the screenplay text. No preamble.

### RAW TRANSCRIPT TO FORMAT ###
{transcript}
"""

DRAMATIZE_INSTRUCTIONS = (
    "You are a strict screenplay formatter. Do not summarize. Output only the "
    "screenplay text — no headers, no commentary, no markdown fences."
)


class AudioAgent(BaseAgent):
    name = StringAttr(default="audioagent")

    provider = StringAttr(default="local")

    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with generating audio files."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with generating audio files."
    )

    def generate(
        self,
        prompt,
        voice_description=None,
        voice_id=None,
        api_key=None,
        provider=None,
    ):
        # BYOK (#227): ``api_key`` overrides this provider's credential
        # for THIS call only — bound to a ContextVar, so concurrent jobs
        # in the same worker never see each other's keys, and nothing is
        # persisted on the agent.
        # #239: ``provider`` overrides the env-derived provider for THIS
        # call only, on a transient client.
        client = resolve_client(self, provider, "TTS_AI_AGENT")
        with client_key_scope(client, api_key):
            return client.generate_audio(
                prompt,
                voice_description=voice_description,
                voice_id=voice_id,
            )

    def transcribe(self, audio_bytes, api_key=None, provider=None):
        """Whisper-only transcription. Returns the verbose-json dict
        ``{"text": str, "segments": [...]}`` from
        ``OpenAIClient.generate_transcription`` (or the equivalent shape
        from ``LocalAIModel.generate_transcription``).

        No LLM pass. No rolling context. The caller is responsible for
        feeding bounded audio (full file, VAD-bounded utterance) and for
        running ``dramatize()`` separately when a screenplay-formatted
        version is wanted.
        """
        # #239: per-call provider override (transient client).
        client = resolve_client(self, provider, "TRANSCRIBE_AI_AGENT")
        log("AudioAgent.transcribe: sending to Whisper...", _print=True)
        # BYOK (#227): ``api_key`` overrides this provider's credential
        # for THIS call only — bound to a ContextVar, so concurrent jobs
        # in the same worker never see each other's keys, and nothing is
        # persisted on the agent.
        with client_key_scope(client, api_key):
            return client.generate_transcription(audio_bytes)

    def dramatize(
        self, transcript, world_context=None, api_key=None, provider=None
    ):
        """Format a complete raw transcript as a TTRPG screenplay.

        Takes the entire transcription text plus a ``world_context`` dict
        (campaign brief, player roster, world elements) so the LLM can
        attribute speakers from real names. Returns formatted screenplay
        text or an empty string on failure.

        Routed through ``TEXT_AI_AGENT`` (typically the same provider as
        text generation generally — currently HPC's gpt-oss:120b).
        """
        if not transcript:
            return ""
        # #239: per-call provider override (transient client).
        client = resolve_client(self, provider, "TEXT_AI_AGENT")
        log(
            f"AudioAgent.dramatize: formatting {len(transcript)}-char transcript "
            f"with {len(world_context or {})} context keys",
            _print=True,
        )
        # BYOK (#227): ``api_key`` overrides this provider's credential
        # for THIS call only — bound to a ContextVar, so concurrent jobs
        # in the same worker never see each other's keys, and nothing is
        # persisted on the agent.
        with client_key_scope(client, api_key):
            return client.generate_text(
                message=DRAMATIZE_PROMPT.format(transcript=transcript),
                additional_instructions=DRAMATIZE_INSTRUCTIONS,
                context=world_context or {},
                temperature=0.3,
            )
