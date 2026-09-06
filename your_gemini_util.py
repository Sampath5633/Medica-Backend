import os
import json
import time
import logging
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load environment variables
load_dotenv()

# API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not set in .env")

# Create client
client = genai.Client(api_key=GEMINI_API_KEY)

MODEL_NAME = "models/gemini-flash-latest"

logging.basicConfig(level=logging.INFO)


def fetch_gemini_response(prompt: str) -> dict:
    max_retries = 3

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.4,
                    max_output_tokens=2048,
                )
            )

            if not response.candidates:
                logging.warning("No candidates returned. Prompt feedback: %s", response.prompt_feedback)
                raise ValueError("No candidates returned")

            finish_reason = response.candidates[0].finish_reason
            logging.info("Gemini finish reason: %s", finish_reason)

            text = response.text.strip()

            # Remove markdown fences if present
            if text.startswith("```"):
                text = text.replace("```json", "").replace("```", "").strip()

            data = json.loads(text)

            # Normalize medications
            if isinstance(data.get("medications"), list):
                data["medications"] = [
                    {"name": m} if isinstance(m, str) else m
                    for m in data["medications"]
                ]

            data.setdefault("lifestyle", [])
            data.setdefault("followup", "Consult a doctor")

            return data

        except Exception as e:
            logging.exception("Gemini attempt %d failed", attempt + 1)
            if attempt < max_retries - 1:
                wait = 2 ** attempt  # 1s, 2s, 4s
                logging.info("Retrying in %ds...", wait)
                time.sleep(wait)
                continue

            return {
                "medications": [],
                "lifestyle": [],
                "followup": "AI unavailable. Please consult a doctor."
            }
