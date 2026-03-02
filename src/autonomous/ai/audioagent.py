import os

from autonomous import log
from autonomous.ai.baseagent import BaseAgent
from autonomous.model.autoattr import StringAttr


class AudioAgent(BaseAgent):
    name = StringAttr(default="audioagent")

    provider = StringAttr(default="local")

    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with generating audio files."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with generating audio files."
    )

    def generate(self, prompt, voice=None):
        return self.get_client(
            os.environ.get("TTS_AI_AGENT", self.provider)
        ).generate_audio(prompt, voice=voice)

    def transcribe(self, audio_bytes, system_context, rolling_context=""):
        """
        1. Transcribes a single chunk of audio.
        2. Passes the raw transcript to the LLM to format as a screenplay.
        """
        local_model = self.get_client(
            os.environ.get("TRANSCRIBE_AI_AGENT", self.provider)
        )

        # 1. Get raw transcript from Whisper
        log("Sending chunk to Whisper...", _print=True)
        raw_result = local_model.generate_transcription(audio_bytes)
        log(raw_result)
        segments = raw_result.get("segments", [])
        if not segments:
            return ""

        # Stitch raw segments into a single block with timestamps
        raw_text = "\n".join(
            [f"[{s['start']}s - {s['end']}s] {s['text']}" for s in segments]
        )

        # 2. Format as Screenplay via LLM
        log("Formatting chunk via LLM...", _print=True)
        llm_prompt = f"""
You are an expert TTRPG Scribe. Rewrite the following raw, automated audio transcript into a clean, readable screenplay format.

GUIDELINES:
1. Identify speakers using the Campaign Context. If unsure, use "UNKNOWN [Number]".
2. Use the Rolling Context to maintain speaker continuity from the previous chunk.
3. Remove verbal tics (um, uh) and off-topic table cross-talk (e.g., passing snacks).
4. KEEP EVERY RELEVANT SPOKEN WORD. Do not summarize the story.
5. Output ONLY the screenplay text. No preamble.

### PREVIOUS CHUNK ENDING (Rolling Context) ###
{rolling_context[-1000:] if rolling_context else "This is the very beginning of the session."}

### RAW TRANSCRIPT TO FORMAT ###
{raw_text}
"""
        # Call generate_text (which uses your Gemma2/Hermes3 model)
        screenplay_chunk = local_model.generate_text(
            message=llm_prompt,
            additional_instructions="You are a strict screenplay formatter. Do not summarize.",
            context={"Campaign Context": system_context},
            temperature=0.3,  # Low temp for high accuracy/formatting adherence
        )

        return screenplay_chunk

    def available_voices(self, filters=[]):
        return self.get_client().list_voices(filters=filters)
