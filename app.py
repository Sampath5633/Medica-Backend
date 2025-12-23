import os
import random
import re
import joblib
import numpy as np
import pandas as pd
import dill
import jwt
import requests
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, request, jsonify, send_file
from flask_mail import Mail, Message
from flask_cors import CORS
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# Import your custom modules
# Ensure these files exist in your project folder
from medication_patterns import default_patterns
from your_gemini_util import fetch_gemini_response

# === Load Environment Variables ===
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

# === Flask App Setup ===
app = Flask(__name__)

# === CORS Configuration ===
# allowing both local and production frontends
CORS(app, resources={r"/*": {"origins": ["http://localhost:5173", "https://medica3.netlify.app"]}},
     supports_credentials=True)

@app.after_request
def apply_cors(response):
    allowed_origins = ["http://localhost:5173", "https://medica3.netlify.app"]
    origin = request.headers.get("Origin")
    if origin in allowed_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
    
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

# === Flask Mail Config ===
app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = os.getenv("MAIL_USE_TLS", "True").lower() == "true"
app.config["MAIL_USE_SSL"] = os.getenv("MAIL_USE_SSL", "False").lower() == "true"
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "fallback_secret")

mail = Mail(app)

# === MongoDB Setup ===
mongo_uri = os.getenv("MONGO_URI")
client = MongoClient(mongo_uri)
db = client["medicalDB"]

# Collections
users_collection = db["users"]
feedback_collection = db["feedback"] 
diagnosis_collection = db["diagnosis_history"]
repredict_collection = db["repredict_history"]
treatment_history_collection = db["treatment_history"]

# === DISEASE SYMPTOMS (Source of Truth) ===
DISEASE_SYMPTOMS = {
  "Addison's Disease": ["fatigue", "muscle weakness", "nausea", "weight loss"],
  "Allergic Reaction": ["itching", "nausea", "rash", "shortness of breath", "swelling"],
  "Alzheimer's Disease": ["confusion", "fatigue", "memory loss", "mood changes"],
  "Anemia": ["dizziness", "fatigue", "pale skin", "shortness of breath", "weakness"],
  "Anxiety Disorder": ["chest pain", "dizziness", "rapid heartbeat", "shortness of breath"],
  "Appendicitis": ["abdominal pain", "fever", "nausea", "vomiting"],
  "Arrhythmia": ["chest pain", "dizziness", "palpitations", "shortness of breath"],
  "Arthritis": ["body pain", "fatigue", "joint pain", "stiffness"],
  "Asthma": ["chest tightness", "cough", "shortness of breath", "wheezing"],
  "COVID-19": ["cough", "fatigue", "fever", "loss of taste", "shortness of breath"],
  "Dengue": ["body pain", "fever", "headache", "joint pain", "rash"],
  "Diabetes": ["blurred vision", "fatigue", "frequent urination", "thirst", "weight loss"],
  "Flu": ["fever", "cough", "sore throat", "runny nose", "body aches"],
  "Malaria": ["body pain", "chills", "fever", "headache", "nausea"],
  "Migraine": ["blurred vision", "headache", "nausea", "sensitivity to light"],
  "Pneumonia": ["chest pain", "chills", "cough", "fever", "shortness of breath"],
  "Typhoid": ["abdominal pain", "diarrhea", "fever", "headache", "weakness"],
  # ... (Keep your full list here)
}

# === ML Model Loading ===
models = {}

def load_models():
    global models
    try:
        base_path = os.path.dirname(os.path.abspath(__file__))
        
        # Load Ensemble
        ensemble_path = os.path.join(base_path, "models", "ensemble_final.pkl")
        if os.path.exists(ensemble_path):
            with open(ensemble_path, "rb") as f:
                models['ensemble'] = dill.load(f)
                # Extract components if needed, or rely on pipeline
            print("✅ Loaded ensemble model!")
        else:
            print("⚠️ Ensemble model file not found.")

        # Load Logistic
        logistic_path = os.path.join(base_path, "models", "best_medical_model_logistic_regression.pkl")
        if os.path.exists(logistic_path):
            models['logistic'] = joblib.load(logistic_path)
            print("✅ Loaded logistic model!")
        else:
            print("⚠️ Logistic model file not found.")

        return True
    except Exception as e:
        print(f"❌ Error loading models: {e}")
        return False

# Load models on startup
load_models()

# === Helper Functions ===

def generate_jwt(email):
    payload = {"email": email, "exp": datetime.utcnow() + timedelta(hours=2)}
    token = jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")
    return token

def get_user_from_token(req):
    auth_header = req.headers.get("Authorization")
    if not auth_header:
        return None
    try:
        token = auth_header.split(" ")[1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        return decoded.get("email")
    except Exception:
        return None

def generate_code():
    return str(random.randint(100000, 999999))

def send_email(subject, recipient, body):
    try:
        msg = Message(subject=subject, sender=app.config["MAIL_USERNAME"], recipients=[recipient])
        msg.body = body
        mail.send(msg)
        print(f"✅ Email sent to {recipient}")
        return True
    except Exception as e:
        print("❌ Email send failed:", e)
        return False

# === Validation Logic (Matches Frontend) ===
def normalize_disease(value):
    return re.sub(r'[^a-z0-9]', '', value.lower())

def is_disease_valid_backend(input_str):
    clean = str(input_str).strip()
    if not clean: return False

    normalized_input = normalize_disease(clean)
    
    # 1. Match against known list
    known_normalized = [normalize_disease(d) for d in DISEASE_SYMPTOMS.keys()]
    if normalized_input in known_normalized:
        return True

    # 2. Strict rules for unknown diseases
    if len(clean) < 6: return False
    if not re.search(r'[a-zA-Z]', clean): return False # Must have letters
    if not re.match(r'^[a-zA-Z0-9\s\'-]+$', clean): return False # No crazy symbols
    
    words = clean.split()
    if len(words) < 2: return False # "Unknown" -> Invalid, "Viral Fever" -> Valid
    if any(len(w) < 3 for w in words): return False # "A B C" -> Invalid

    return True

# === ML Preprocessing Helpers ===

def get_ensemble_proba(ensemble, X):
    # This helper handles extracting probas from the specific ensemble structure you have
    lr = ensemble.lr
    rf = ensemble.rf
    svm = ensemble.svm
    xgb = ensemble.xgb

    try:
        X_arr = X.toarray()
    except Exception:
        X_arr = np.asarray(X)

    p1 = lr.predict_proba(X)
    p2 = rf.predict_proba(X_arr)
    
    # SVM logic
    try:
        p3 = svm.predict_proba(X)
    except Exception:
        df = svm.decision_function(X)
        if df.ndim == 1:
            df = np.vstack([-df, df]).T
        exp = np.exp(df - np.max(df, axis=1, keepdims=True))
        p3 = exp / exp.sum(axis=1, keepdims=True)

    p4 = xgb.predict_proba(X_arr)

    return (np.asarray(p1).astype(float) + np.asarray(p2).astype(float) + np.asarray(p3).astype(float) + np.asarray(p4).astype(float)) / 4.0

def preprocess_input(data):
    try:
        df_dict = {
            "Symptoms": "",
            "Blood Pressure": data.get("blood_pressure", "0/0"),
            "Heart Rate (bpm)": int(data.get("heart_rate", 0)),
            "Age": int(data.get("age", 0)),
            "Temperature (°F)": float(data.get("temperature", 0)),
            "Oxygen Saturation (%)": int(data.get("oxygen_saturation", 0))
        }

        sym = data.get("symptoms", "")
        if isinstance(sym, list):
            df_dict["Symptoms"] = ", ".join(sym)
        else:
            df_dict["Symptoms"] = str(sym)

        df = pd.DataFrame([df_dict])
        
        # Use ensemble's built-in preprocessor
        if "ensemble" in models:
            features = models["ensemble"].preprocess(df)
            return features, df_dict["Symptoms"]
        else:
            return None, ""
            
    except Exception as e:
        print("❌ Preprocessing error:", e)
        return None, ""

def top_k_from_proba(probs, classes, k=5):
    top_indices = np.argsort(probs)[-k:][::-1]
    top_preds = [{"disease": str(classes[i]), "confidence": float(probs[i])} for i in top_indices]
    return top_preds

def boost_probs_by_selected(probs, classes, top_diseases, selected_symptoms, boost_per_match=0.12):
    try:
        new_probs = probs.astype(float).copy()
        sel = [s.strip().lower() for s in (selected_symptoms or []) if s]
        ds_map = {d: [s.lower() for s in DISEASE_SYMPTOMS.get(d, [])] for d in DISEASE_SYMPTOMS.keys()}
        
        class_names = [str(c) for c in classes]
        class_lookup = {class_names[i]: i for i in range(len(class_names))}

        for disease in (top_diseases or []):
            if disease in class_lookup:
                idx = class_lookup[disease]
                known_symptoms = ds_map.get(disease, [])
                matches = sum(1 for s in sel if s in known_symptoms)
                if matches > 0:
                    factor = 1.0 + (matches * boost_per_match)
                    new_probs[idx] = new_probs[idx] * factor
        
        total = new_probs.sum()
        if total > 0:
            new_probs = new_probs / total
        return new_probs
    except Exception:
        return probs

# ==========================================================
# ROUTES
# ==========================================================

# --- Auth Routes (Register, Login, Reset) ---
@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(force=True)
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"message": "Missing email or password"}), 400

    if users_collection.find_one({"email": email}):
        return jsonify({"message": "User already exists"}), 400

    hashed_password = generate_password_hash(password)
    users_collection.insert_one({
        "email": email,
        "password": hashed_password,
        "is_verified": False
    })
    return jsonify({"message": "Registration successful"}), 201

@app.route("/api/login-step1", methods=["POST"])
def login_step1():
    try:
        data = request.get_json(force=True)
        email = data.get("email")
        password = data.get("password")

        user = users_collection.find_one({"email": email})
        if not user or not check_password_hash(user.get("password"), password):
            return jsonify({"message": "Invalid credentials"}), 401

        if user.get("is_verified", False):
            token = generate_jwt(email)
            return jsonify({"token": token}), 200

        code = generate_code()
        users_collection.update_one(
            {"email": email},
            {"$set": {"verification_code": code, "code_expiry": datetime.utcnow() + timedelta(minutes=10)}}
        )
        send_email("Your MEDICA Verification Code", email, f"Your verification code is: {code}")
        return jsonify({"step": 2}), 200
    except Exception as e:
        return jsonify({"message": "Server Error", "error": str(e)}), 500

@app.route("/api/login-step2", methods=["POST"])
def login_step2():
    data = request.get_json(force=True)
    email = data.get("email")
    code = data.get("code")

    user = users_collection.find_one({"email": email})
    if not user:
        return jsonify({"message": "User not found"}), 404

    if user.get("verification_code") != code:
        return jsonify({"message": "Invalid code"}), 401

    if datetime.utcnow() > user.get("code_expiry", datetime.utcnow()):
        return jsonify({"message": "Code expired"}), 401

    users_collection.update_one(
        {"email": email},
        {"$unset": {"verification_code": "", "code_expiry": ""}, "$set": {"is_verified": True}}
    )
    token = generate_jwt(email)
    return jsonify({"message": "Login successful", "token": token}), 200

@app.route("/api/send-reset-code", methods=["POST"])
def send_reset_code():
    data = request.get_json(force=True)
    email = data.get("email")
    
    user = users_collection.find_one({"email": email})
    if not user:
        return jsonify({"message": "User not found"}), 404

    code = generate_code()
    users_collection.update_one(
        {"email": email},
        {"$set": {"reset_code": code, "reset_expiry": datetime.utcnow() + timedelta(minutes=10)}}
    )
    send_email("MEDICA Password Reset", email, f"Your reset code is: {code}")
    return jsonify({"message": "Reset code sent"}), 200

@app.route("/api/reset-password", methods=["POST"])
def reset_password():
    data = request.get_json(force=True)
    email = data.get("email")
    code = data.get("code")
    new_password = data.get("newPassword")

    user = users_collection.find_one({"email": email})
    if not user:
        return jsonify({"message": "User not found"}), 404

    if user.get("reset_code") != code:
        return jsonify({"message": "Invalid code"}), 401

    hashed_password = generate_password_hash(new_password)
    users_collection.update_one(
        {"email": email},
        {"$set": {"password": hashed_password}, "$unset": {"reset_code": "", "reset_expiry": ""}}
    )
    return jsonify({"message": "Password reset successful"}), 200


# --- ML Routes (Predict & Repredict) ---

@app.route("/predict", methods=["POST"])
def predict():
    try:
        data = request.get_json(force=True)
        features, symptom_text = preprocess_input(data)
        
        if features is None:
            return jsonify({"error": "Invalid input or models not loaded"}), 400

        predictions = {}

        # 1. Logistic
        if "logistic" in models:
            probs = models["logistic"].predict_proba(features)[0]
            classes = models["logistic"].classes_
            top_preds = top_k_from_proba(probs, classes, k=5)
            predictions["logistic"] = {
                "prediction": top_preds[0]["disease"],
                "confidence": float(top_preds[0]["confidence"]),
                "top_predictions": top_preds
            }

        # 2. Ensemble
        if "ensemble" in models:
            probs_all = get_ensemble_proba(models["ensemble"], features)
            probs = probs_all[0]
            try:
                classes = models["ensemble"].encoder.classes_
            except:
                classes = models["logistic"].classes_ 
            
            top_preds = top_k_from_proba(probs, classes, k=5)
            predictions["ensemble"] = {
                "prediction": top_preds[0]["disease"],
                "confidence": float(top_preds[0]["confidence"]),
                "top_predictions": top_preds
            }

        # Save History
        user_email = get_user_from_token(request)
        if user_email:
            diagnosis_collection.insert_one({
                "email": user_email,
                "input": data,
                "predictions": predictions,
                "symptom_text": symptom_text,
                "createdAt": datetime.utcnow()
            })

        return jsonify({
            "result": predictions,
            "symptom_text": symptom_text
        })
        
    except Exception as e:
        print("❌ Prediction error:", e)
        return jsonify({"error": str(e)}), 500

@app.route("/repredict", methods=["POST"])
def repredict():
    try:
        data = request.get_json(force=True)
        selected_symptoms = data.get("selected_symptoms", []) or []
        top_diseases_from_front = data.get("top_diseases", []) or []

        features, symptom_text = preprocess_input(data)
        if features is None:
            return jsonify({"error": "Invalid input"}), 400

        result = {}

        for model_key in ["logistic", "ensemble"]:
            if model_key not in models: continue

            if model_key == "ensemble":
                raw_probs = get_ensemble_proba(models["ensemble"], features)[0]
                try:
                    classes = models["ensemble"].encoder.classes_
                except:
                    classes = models["logistic"].classes_
            else:
                raw_probs = models["logistic"].predict_proba(features)[0]
                classes = models["logistic"].classes_

            original_top = top_k_from_proba(raw_probs, classes, k=10)
            if not original_top: continue

            candidates = top_diseases_from_front if top_diseases_from_front else [p["disease"] for p in original_top[:3]]

            boosted_probs = boost_probs_by_selected(raw_probs, classes, candidates, selected_symptoms)
            boosted_top = top_k_from_proba(boosted_probs, classes, k=10)
            
            final_top = boosted_top if boosted_top else original_top
            best = final_top[0]

            result[model_key] = {
                "prediction": best["disease"],
                "confidence": float(best["confidence"]),
                "top_predictions": final_top[:5]
            }

        # Save History
        user_email = get_user_from_token(request)
        if user_email:
            repredict_collection.insert_one({
                "email": user_email,
                "selected_symptoms": selected_symptoms,
                "results": result,
                "createdAt": datetime.utcnow()
            })

        return jsonify({
            "result": result,
            "repredict": True,
            "symptom_text": symptom_text
        }), 200

    except Exception as e:
        print("❌ Repredict error:", e)
        return jsonify({"error": str(e)}), 500


# --- Treatment & History Routes ---

@app.route("/api/treatment", methods=["POST"])
def generate_treatment():
    try:
        data = request.get_json(force=True)
        disease = data.get("disease", "").strip()
        symptoms = data.get("symptoms", [])
        age = data.get("age")
        blood_group = data.get("blood_group", "")
        duration = data.get("duration")

        # 🛑 BACKEND VALIDATION: MATCHES FRONTEND LOGIC
        if not is_disease_valid_backend(disease):
             return jsonify({
                 "error": "Invalid disease name. System only allows known or medically plausible names."
             }), 400

        if not disease or not symptoms or not age:
            return jsonify({"error": "Missing required patient information"}), 400

        # Construct Gemini Prompt
        prompt = f"""
        You are an AI medical assistant.
        Patient Details:
        - Disease: {disease}
        - Age: {age}
        - Blood Group: {blood_group}
        - Symptoms: {', '.join(symptoms) if isinstance(symptoms, list) else str(symptoms)}
        - Duration: {duration}

        Instructions:
        1. Generate exactly 3 medications strictly based on the disease.
        2. Return a JSON ONLY format:
        {{
          "medications": [
            {{"name": "MedName", "intake": "1-0-1", "timing": "after food"}},
            ...
          ],
          "lifestyle": ["tip1", "tip2"],
          "followup": "Consult doctor in X days"
        }}
        """

        treatment_data = fetch_gemini_response(prompt)

        # Enforce pattern overrides if Gemini misses them
        normalized_patterns = {k.lower(): v for k, v in default_patterns.items()}
        for med in treatment_data.get("medications", []):
            med_name_lower = med["name"].lower()
            if med_name_lower in normalized_patterns:
                pattern = normalized_patterns[med_name_lower]
                parts = pattern.split(' ')
                med["intake"] = parts[0]
                med["timing"] = ' '.join(parts[1:])
        
        full_prescription = {
            "disease": disease,
            "age": age,
            "symptoms": symptoms,
            "blood_group": blood_group,
            "duration": duration,
            "treatment": treatment_data
        }

        user_email = get_user_from_token(request)
        if user_email:
            treatment_history_collection.insert_one({
                "email": user_email,
                "prescription": full_prescription,
                "generated_by": "Gemini",
                "createdAt": datetime.utcnow()
            })

        return jsonify(full_prescription), 200

    except Exception as e:
        print(f"❌ Treatment endpoint error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/user/history", methods=["GET"])
def get_user_history():
    user_email = get_user_from_token(request)
    if not user_email:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        diagnosis = list(diagnosis_collection.find({"email": user_email}, {"_id": 0}).sort("createdAt", -1))
        treatments = list(treatment_history_collection.find({"email": user_email}, {"_id": 0}).sort("createdAt", -1))
        repredicts = list(repredict_collection.find({"email": user_email}, {"_id": 0}).sort("createdAt", -1))

        return jsonify({
            "diagnosis_history": diagnosis,
            "treatment_history": treatments,
            "repredict_history": repredicts
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- PDF & Feedback ---
@app.route("/api/treatment/download", methods=["POST"])
def download_prescription():
    try:
        data = request.get_json(force=True)
        prescription = data 
        filename = "prescription.pdf"
        os.makedirs("prescriptions", exist_ok=True)
        filepath = os.path.join("prescriptions", filename)

        c = canvas.Canvas(filepath, pagesize=letter)
        width, height = letter

        c.setFont("Helvetica-Bold", 16)
        c.drawString(100, height - 50, "Doctor’s Prescription")

        y = height - 90
        c.setFont("Helvetica", 12)
        c.drawString(100, y, f"Disease: {prescription.get('disease', '')}")
        y -= 20
        c.drawString(100, y, f"Age: {prescription.get('age', '')}")
        y -= 20
        c.drawString(100, y, f"Blood Group: {prescription.get('blood_group', '')}")
        
        y -= 40
        c.setFont("Helvetica-Bold", 14)
        c.drawString(100, y, "Medications:")
        y -= 20
        c.setFont("Helvetica", 12)
        for med in prescription.get("treatment", {}).get("medications", []):
            c.drawString(120, y, f"- {med['name']} ({med.get('intake','')}, {med.get('timing','')})")
            y -= 20

        c.save()
        return send_file(filepath, as_attachment=True)
    except Exception as e:
        return jsonify({"error": "Could not generate PDF"}), 500

@app.route("/api/submit-feedback", methods=["POST"])
def submit_feedback():
    try:
        data = request.json
        email = data.get("email", "anonymous")
        message = data.get("message", "")
        if not message:
            return jsonify({"success": False, "message": "Required fields missing"}), 400
        
        feedback_collection.insert_one({
            "email": email, "message": message, "timestamp": datetime.utcnow()
        })
        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/ping-db", methods=["GET"])
def ping_db():
    try:
        count = users_collection.count_documents({})
        return jsonify({"message": "MongoDB connected ✅", "user_count": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# === Entry Point ===
if __name__ == '__main__':
    # Use environment port for Render
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
