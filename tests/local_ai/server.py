import io
import os
import shutil

import soundfile as sf
import torch
from datasets import load_dataset
from faster_whisper import WhisperModel
from flask import Flask, jsonify, request, send_file

# Import BOTH pipelines
from optimum.intel import OVStableDiffusionImg2ImgPipeline, OVStableDiffusionPipeline
from PIL import Image
from sentence_transformers import SentenceTransformer
from transformers import SpeechT5ForTextToSpeech, SpeechT5HifiGan, SpeechT5Processor

model_path = "./ov_model_cache"


app = Flask(__name__)

# --- 1. Audio Transcription (Whisper) ---
print("Loading Whisper...")
stt_model = WhisperModel("medium.en", device="cpu", compute_type="int8")

# --- 2. Image Generation (OpenVINO) ---
local_model_path = "./ov_model_cache"
base_model_id = "runwayml/stable-diffusion-v1-5"

print("Loading Stable Diffusion (T2I)...")
# 1. Try to load from local cache
if os.path.exists(local_model_path) and len(os.listdir(local_model_path)) > 0:
    try:
        print(f"Loading from local cache: {local_model_path}")
        t2i_pipe = OVStableDiffusionPipeline.from_pretrained(
            local_model_path, device="CPU"
        )
        print("Successfully loaded from cache.")
    except Exception as e:
        print(f"Cache corrupted or incomplete: {e}")
        print("Deleting corrupted cache and re-downloading...")
        # Do not use rmtree on the root folder. Delete contents only.
        for filename in os.listdir(model_path):
            file_path = os.path.join(model_path, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print(f"Failed to delete {file_path}. Reason: {e}")

        # Re-download immediately
        t2i_pipe = OVStableDiffusionPipeline.from_pretrained(base_model_id, export=True)
        t2i_pipe.save_pretrained(local_model_path)
else:
    # 2. If cache doesn't exist at all, download
    print("Cache missing. Downloading model...")
    t2i_pipe = OVStableDiffusionPipeline.from_pretrained(base_model_id, export=True)
    t2i_pipe.save_pretrained(local_model_path)

# 2. Load Text-to-Image Pipeline
t2i_pipe = OVStableDiffusionPipeline.from_pretrained(
    local_model_path, ov_config={"PERFORMANCE_HINT": "LATENCY", "NUM_STREAMS": "1"}
)
t2i_pipe.reshape(batch_size=1, height=512, width=512, num_images_per_prompt=1)
t2i_pipe.compile()

# 3. Load Image-to-Image Pipeline (Independent Load)
print("Loading Stable Diffusion (Img2Img)...")
i2i_pipe = OVStableDiffusionImg2ImgPipeline.from_pretrained(
    local_model_path, ov_config={"PERFORMANCE_HINT": "LATENCY", "NUM_STREAMS": "1"}
)
i2i_pipe.reshape(batch_size=1, height=512, width=512, num_images_per_prompt=1)
i2i_pipe.compile()

# --- 3. Text-to-Speech (SpeechT5) ---
print("Loading TTS...")
tts_processor = SpeechT5Processor.from_pretrained("microsoft/speecht5_tts")
tts_model = SpeechT5ForTextToSpeech.from_pretrained("microsoft/speecht5_tts")
vocoder = SpeechT5HifiGan.from_pretrained("microsoft/speecht5_hifigan")
embeddings_dataset = load_dataset(
    "Matthijs/cmu-arctic-xvectors",
    split="validation",
    trust_remote_code=True,
)

print("Loading Embedding Model...")
# all-MiniLM-L6-v2 is fast, small (80MB), and excellent for RAG
embed_model = SentenceTransformer("all-MiniLM-L6-v2")

speaker_embeddings = {
    "default": torch.tensor(embeddings_dataset[7306]["xvector"]).unsqueeze(0),
}


@app.route("/health", methods=["GET"])
def health():
    # If the models are loaded, this returns 200
    return jsonify({"status": "ready"})


@app.route("/transcribe", methods=["POST"])
def transcribe():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files["file"]
    segments, info = stt_model.transcribe(io.BytesIO(file.read()), beam_size=5)
    return jsonify({"text": " ".join([segment.text for segment in segments])})


@app.route("/generate-image", methods=["POST"])
def generate_image():
    # 1. Get Prompt
    prompt = request.form.get("prompt")
    negative_prompt = request.form.get("negative_prompt", "")

    if not prompt:
        return jsonify({"error": "No prompt provided"}), 400

    # 2. Check for Reference Image (Img2Img)
    image_file = request.files.get("file")

    if image_file:
        # Load and process input image
        init_image = Image.open(image_file).convert("RGB")
        init_image = init_image.resize((512, 512))

        # Generate with Img2Img
        # strength=0.75 means "modify the image significantly but keep structure"
        image = i2i_pipe(
            prompt=prompt,
            negative_prompt=negative_prompt,
            image=init_image,
            strength=0.75,
            num_inference_steps=20,
        ).images[0]
    else:
        # Generate with Standard Text-to-Image
        image = t2i_pipe(
            prompt, negative_prompt=negative_prompt, num_inference_steps=20
        ).images[0]

    # 3. Return Result
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format="WEBP")
    img_byte_arr.seek(0)
    return send_file(img_byte_arr, mimetype="image/webp")


@app.route("/tts", methods=["POST"])
def tts():
    text = request.json.get("text")
    inputs = tts_processor(text=text, return_tensors="pt")
    speech = tts_model.generate_speech(
        inputs["input_ids"], speaker_embeddings["default"], vocoder=vocoder
    )
    buffer = io.BytesIO()
    sf.write(buffer, speech.numpy(), samplerate=16000, format="WAV")
    buffer.seek(0)
    return send_file(buffer, mimetype="audio/wav")


@app.route("/embeddings", methods=["POST"])
def generate_embeddings():
    data = request.json
    text = data.get("text")
    if not text:
        return jsonify({"error": "No text provided"}), 400

    # Generate vector and convert to standard Python list
    vector = embed_model.encode(text).tolist()
    return jsonify({"embedding": vector})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005)
