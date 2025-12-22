import os
import json
from dotenv import load_dotenv
from google import genai

# Load environment variables
load_dotenv()

# API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not set in .env")

# Create client
client = genai.Client(api_key=GEMINI_API_KEY)

MODEL_NAME = "models/gemini-flash-latest"

def fetch_gemini_response(prompt: str) -> dict:
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )

        text = response.text.strip()

        # Remove markdown if present
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
        print("❌ Gemini API error:", e)
        return {
            "medications": [],
            "lifestyle": [],
            "followup": "AI unavailable. Please consult a doctor."
        }
