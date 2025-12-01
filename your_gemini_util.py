import os
import json
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not set in .env file")

genai.configure(api_key=GEMINI_API_KEY)

def fetch_gemini_response(prompt: str) -> dict:
    """
    Calls the Gemini API and returns a structured treatment plan.
    Ensures the response is valid JSON and medications are dicts with names.
    """
    try:
        model = genai.GenerativeModel(
            'gemini-2.5-pro',
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.4,
                max_output_tokens=2048,
            )
        )

        response = model.generate_content(prompt)
        raw_text = ""

        # Extract text safely
        if response.candidates and response.candidates[0].content.parts:
            raw_text = response.candidates[0].content.parts[0].text.strip()
        elif hasattr(response, "text"):
            raw_text = response.text.strip()

        # Remove markdown fences if present
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:].strip()
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3].strip()

        # Attempt JSON parsing
        try:
            treatment_data = json.loads(raw_text)

            # Ensure medications are dictionaries
            if isinstance(treatment_data.get("medications"), list):
                treatment_data["medications"] = [
                    med if isinstance(med, dict) and "name" in med else {"name": str(med)}
                    for med in treatment_data["medications"]
                ]

            # Ensure lifestyle and followup keys exist
            treatment_data.setdefault("lifestyle", [])
            treatment_data.setdefault("followup", "Consult a doctor for follow-up.")

        except json.JSONDecodeError as e:
            print("⚠️ Failed to parse Gemini output as JSON:", e)
            print("Raw output:", raw_text)
            treatment_data = {
                "medications": [],
                "lifestyle": [],
                "followup": "Could not generate a structured plan. Please consult a doctor."
            }

        return treatment_data

    except Exception as e:
        print(f"❌ Gemini API error: {e}")
        return {
            "medications": [],
            "lifestyle": [],
            "followup": "Error communicating with the AI. Please consult a doctor."
        }
