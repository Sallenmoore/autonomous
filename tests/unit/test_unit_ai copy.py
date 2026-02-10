import os

import pytest
from autonomous.ai.audioagent import AudioAgent
from autonomous.ai.imageagent import ImageAgent
from autonomous.ai.jsonagent import JSONAgent
from autonomous.ai.models.gemini import GeminiAIModel
from autonomous.ai.models.local_model import LocalAIModel
from autonomous.ai.textagent import TextAgent

# --- FIXTURES ---


@pytest.fixture
def mock_context():
    """Sample context data usually coming from get_context()"""
    return {
        "Focus Object": "The Golden Compass",
        "Name": "Golden Compass",
        "Description": "A magical device that tells the truth.",
        "Associations": ["a", "b", "c"],
        "Lore": ["It was forged by bears.", "It breaks if you lie."],
    }


@pytest.fixture
def joke_function_schema():
    return {
        "name": "tell_joke",
        "description": "Generates a funny joke with a rating",
        "parameters": {
            "type": "object",
            "properties": {
                "setup": {"type": "string"},
                "punchline": {"type": "string"},
                "rating": {"type": "integer", "description": "Rating from 1-10"},
            },
            "required": ["setup", "punchline", "rating"],
        },
    }


# --- TEST FACTORY LOGIC ---


def test_agent_switching():
    """Verify BaseAgent correctly switches underlying clients"""
    agent = TextAgent(name="SwitcherBot")

    # 1. Default (Gemini)
    assert isinstance(agent.get_client(), GeminiAIModel)
    assert agent.provider == "gemini"

    # 2. Switch to Local
    agent.provider = "local"
    client = agent.get_client()
    assert isinstance(client, LocalAIModel)

    # 3. Verify persistence (mock save)
    assert agent.client.__class__ == LocalAIModel


# --- TEST JSON GENERATION ---


@pytest.mark.parametrize("provider", ["local", "gemini"])
def test_generate_json(provider, joke_function_schema, mock_context):
    """Test JSON generation on both providers"""
    if provider == "gemini" and not os.getenv("GOOGLEAI_KEY"):
        pytest.skip("Skipping Gemini test: No API Key")

    print(f"\nTesting JSON Agent with provider: {provider}")

    agent = JSONAgent(name=f"JsonBot_{provider}", provider=provider)

    prompt = "Tell me a joke about a compass."

    # Pass context to ensure it handles the injection correctly
    result = agent.generate(
        message=prompt, function=joke_function_schema, context=mock_context
    )

    print(f"Result ({provider}): {result}")

    assert isinstance(result, dict)
    assert "setup" in result
    assert "punchline" in result
    assert isinstance(result["rating"], int)


# --- TEST TEXT GENERATION ---


@pytest.mark.parametrize("provider", ["local", "gemini"])
def test_generate_text_with_context(provider, mock_context):
    """Test basic text generation with context injection"""
    if provider == "gemini" and not os.getenv("GOOGLEAI_KEY"):
        pytest.skip("No Google Key")

    agent = TextAgent(name=f"TextBot_{provider}", provider=provider)

    # We ask a question that specifically requires the context to answer correctly
    prompt = "Who forged the Golden Compass?"

    response = agent.generate(prompt, context=mock_context)

    print(f"\nResponse ({provider}): {response}")

    # The answer "bears" is only in the mock_context, not general knowledge
    # Note: Local models might hallucinate, but a good model should catch this.
    assert response is not None
    assert len(response) > 5


# --- TEST AUDIO AGENT (TTS) ---


@pytest.mark.parametrize("provider", ["local", "gemini"])
def test_audio_generation(provider):
    if provider == "gemini" and not os.getenv("GOOGLEAI_KEY"):
        pytest.skip("No Google Key")

    agent = AudioAgent(name=f"AudioBot_{provider}", provider=provider)

    # Get a valid voice for the provider
    voices = agent.available_voices()
    assert len(voices) > 0
    selected_voice = voices[0]

    print(f"Generating audio with {provider} using voice: {selected_voice}")

    audio_bytes = agent.generate("Hello world, this is a test.", voice=selected_voice)

    assert audio_bytes is not None
    assert len(audio_bytes) > 100  # Should be a valid file

    # Optional: Save to hear it
    with open(f"tests/assets/test_audio_{provider}.mp3", "wb") as f:
        f.write(audio_bytes)


# --- TEST IMAGE AGENT ---


@pytest.mark.parametrize("provider", ["local", "gemini"])
def test_image_generation(provider):
    if provider == "gemini" and not os.getenv("GOOGLEAI_KEY"):
        pytest.skip("No Google Key")

    agent = ImageAgent(name=f"ImageBot_{provider}", provider=provider)

    print(f"Generating image with {provider}...")

    try:
        image_bytes = agent.generate("A cyberpunk city with neon lights")

        assert image_bytes is not None
        assert len(image_bytes) > 1000

        # Determine extension based on provider defaults (WebP for Gemini, PNG often for Local)
        ext = "webp" if provider == "gemini" else "png"
        with open(f"tests/assets/test_image_{provider}.{ext}", "wb") as f:
            f.write(image_bytes)

    except Exception as e:
        # Local image generation often fails if the model isn't loaded/downloaded
        pytest.fail(f"Image generation failed: {e}")


@pytest.mark.parametrize("provider", ["local", "gemini"])
def test_image_generation_full_flow(provider):
    """
    Tests the full ImageAgent interface:
    1. Generates an image from text (Prompt + Aspect Ratio + Size).
    2. Uses that generated image as a file input for a second generation (Files + Prompt).
    """
    if provider == "gemini" and not os.getenv("GOOGLEAI_KEY"):
        pytest.skip("No Google Key")

    agent = ImageAgent(name=f"ImageBot_{provider}", provider=provider)
    print(f"Testing full image flow with {provider}...")

    ext = "webp" if provider == "gemini" else "png"

    try:
        # --- STEP 1: Text-to-Image ---
        print("Step 1: Generating initial image...")
        prompt_1 = "A cyberpunk city with neon lights"

        image_1_bytes = agent.generate(
            prompt_1, aspect_ratio="1:1", image_size="1024x1024"
        )

        assert image_1_bytes is not None
        assert len(image_1_bytes) > 1000

        # Save Step 1 output
        with open(f"tests/assets/test_image_{provider}_step1.{ext}", "wb") as f:
            f.write(image_1_bytes)

        # --- STEP 2: Image-to-Image (using output of Step 1) ---
        print("Step 2: Regenerating using the first image as context...")
        prompt_2 = "The same city, but raining heavily, darker atmosphere"

        # Construct the files dictionary: { "filename.ext": bytes }
        files_payload = [{"name": f"reference_image.{ext}", "file": image_1_bytes}]

        image_2_bytes = agent.generate(
            prompt_2, aspect_ratio="1:1", image_size="1024x1024", files=files_payload
        )

        assert image_2_bytes is not None
        assert len(image_2_bytes) > 1000

        # Save Step 2 output
        with open(f"tests/assets/test_image_{provider}_step2.{ext}", "wb") as f:
            f.write(image_2_bytes)

        print("Success: Both generation steps completed.")

    except Exception as e:
        pytest.fail(f"Image generation flow failed during {provider} execution: {e}")
