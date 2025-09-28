import os
import numpy as np
import requests
import random
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_mail import Mail, Message
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path
import numpy as np
from medication_patterns import default_patterns
from fastapi import FastAPI
from fastapi.responses import FileResponse
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from flask import Flask, request, jsonify, send_file
# Temporary storage for prescriptions (you may replace with DB)
PRESCRIPTIONS = {}
from flask import Flask, request, jsonify
from your_gemini_util import fetch_gemini_response 
from flask_cors import CORS
from flask_mail import Mail, Message
from datetime import datetime, timedelta
from dotenv import load_dotenv
import traceback
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, request, jsonify
from pymongo import MongoClient
from flask_cors import CORS
from datetime import datetime


# === Load Environment Variables ===
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

# === Flask Setup ===
app = Flask(__name__)

# === Enable CORS for frontend ===
CORS(app, origins=["https://medica3.netlify.app"], supports_credentials=True)


@app.before_request
def log_request_info():
    print(f"➡️ {request.method} {request.path}")
    if request.method == 'OPTIONS':
        print("🔄 Handling preflight OPTIONS request")

# === Mail Configuration ===
gmail_user = os.getenv("MAIL_USERNAME")
app.config.update(
    MAIL_SERVER=os.getenv("MAIL_SERVER"),
    MAIL_PORT=int(os.getenv("MAIL_PORT", 587)),
    MAIL_USERNAME=gmail_user,
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
    MAIL_USE_TLS=os.getenv("MAIL_USE_TLS", "True") == "True",
    MAIL_USE_SSL=os.getenv("MAIL_USE_SSL", "False") == "True"
)
mail = Mail(app)

# === MongoDB Setup ===
mongo_uri = os.getenv("MONGO_URI")
client = MongoClient(mongo_uri)
db = client["medicalDB"]
users = db["users"]
feedback_collection = db["feedbacks"]   

# === Utility: Send Email ===
def send_verification_email(email, code):
    msg = Message("Your Verification Code", sender=gmail_user, recipients=[email])
    msg.body = f"Your verification code is: {code}"
    mail.send(msg)
    print(f"✅ Email sent to {email} with code {code}")

# === Register Endpoint ===
@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(force=True)
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"message": "Missing email or password"}), 400

    if users.find_one({"email": email}):
        return jsonify({"message": "User already exists"}), 400

    hashed_password = generate_password_hash(password)
    users.insert_one({
        "email": email,
        "password": hashed_password,
        "is_verified": False
    })

    return jsonify({"message": "Registration successful"}), 201

# === Login Step 1 ===
@app.route("/api/login-step1", methods=["POST"])
def login_step1():
    try:
        data = request.get_json()
        email = data.get("email")
        password = data.get("password")

        if not email or not password:
            return jsonify({"message": "Email and password are required"}), 400

        user = users.find_one({"email": email})
        if not user:
            return jsonify({"message": "User not found"}), 404

        if not check_password_hash(user["password"], password):
            return jsonify({"message": "Invalid password"}), 401

        if user.get("is_verified", False):
            return jsonify({"token": "dummy_token"}), 200

        # Generate verification code
        verification_code = str(random.randint(100000, 999999))
        code_expiry = datetime.now(timezone.utc) + timedelta(minutes=10)

        # Store in DB
        users.update_one(
            {"email": email},
            {"$set": {"verification_code": verification_code, "code_expiry": code_expiry}}
        )

        # Send email
        try:
            send_verification_email(email, verification_code)
        except Exception as e:
            print("❌ Failed to send verification email:", e)
            return jsonify({"message": "Failed to send verification email", "error": str(e)}), 500

        return jsonify({"step": 2, "message": "Verification code sent"}), 200

    except Exception as e:
        print("❌ login-step1 error:", e)
        return jsonify({"message": "Login step 1 failed", "error": str(e)}), 500

@app.route("/api/login-step2", methods=["POST"])
def login_step2():
    try:
        data = request.get_json()
        email = data.get("email")
        code = data.get("code")
        print("Login Step 2 - email:", email, "code:", code)

        user = users.find_one({"email": email})
        print("User found:", user)

        if not user:
            return jsonify({"message": "User not found"}), 404

        if user.get("is_verified", False):
            return jsonify({"message": "Already verified", "token": "dummy_token"}), 200

        if user.get("verification_code") != code:
            return jsonify({"message": "Invalid verification code"}), 401

        code_expiry = user.get("code_expiry")
        if not code_expiry:
            return jsonify({"message": "Verification code missing"}), 400

        # Ensure timezone-aware comparison
        now = datetime.now(timezone.utc)
        if now > code_expiry:
            return jsonify({"message": "Verification code expired"}), 401

        # Update user as verified and remove verification code
        users.update_one(
            {"email": email},
            {
                "$unset": {"verification_code": "", "code_expiry": ""},
                "$set": {"is_verified": True}
            }
        )
        print(f"✅ User {email} verified successfully")

        return jsonify({"message": "Login successful", "token": "dummy_token"}), 200

    except Exception as e:
        print("❌ /api/login-step2 error:", e)
        return jsonify({"message": "Login step 2 failed", "error": str(e)}), 500



# === Send Reset Code ===
@app.route("/api/send-reset-code", methods=["POST"])
def send_reset_code():
    try:
        data = request.get_json()
        email = data.get("email")

        if not email:
            return jsonify({"message": "Email is required"}), 400

        user = users.find_one({"email": email})
        if not user:
            return jsonify({"message": "Email not found"}), 404

        reset_code = str(random.randint(100000, 999999))
        reset_expiry = datetime.now(timezone.utc) + timedelta(minutes=10)

        # Store reset code
        users.update_one(
            {"email": email},
            {"$set": {"reset_code": reset_code, "reset_expiry": reset_expiry}}
        )

        # Send email
        try:
            msg = Message("Password Reset Code", sender=gmail_user, recipients=[email])
            msg.body = f"Your password reset code is: {reset_code}"
            mail.send(msg)
            print(f"✅ Reset code sent to {email}")
        except Exception as e:
            print("❌ Failed to send reset email:", e)
            return jsonify({"message": "Failed to send reset email", "error": str(e)}), 500

        return jsonify({"message": "Reset code sent"}), 200

    except Exception as e:
        print("❌ send-reset-code error:", e)
        return jsonify({"message": "Failed to send reset code", "error": str(e)}), 500

@app.route("/api/reset-password", methods=["POST"])
def reset_password():
    try:
        data = request.get_json()
        email = data.get("email")
        code = data.get("code")
        new_password = data.get("newPassword")
        print("Reset password - email:", email, "code:", code)

        user = users.find_one({"email": email})
        print("User found:", user)

        if not user:
            return jsonify({"message": "User not found"}), 404

        if user.get("reset_code") != code:
            return jsonify({"message": "Invalid reset code"}), 401

        reset_expiry = user.get("reset_expiry")
        if not reset_expiry:
            return jsonify({"message": "Reset expiry missing"}), 400

        now = datetime.now(timezone.utc)
        if now > reset_expiry:
            return jsonify({"message": "Reset code expired"}), 401

        # Update password
        hashed_password = generate_password_hash(new_password)
        users.update_one(
            {"email": email},
            {
                "$set": {"password": hashed_password},
                "$unset": {"reset_code": "", "reset_expiry": ""}
            }
        )
        print(f"✅ Password reset successfully for {email}")

        return jsonify({"message": "Password reset successful"}), 200

    except Exception as e:
        print("❌ /api/reset-password error:", e)
        return jsonify({"message": "Failed to reset password", "error": str(e)}), 500


# === Proxy to Hugging Face for Prediction ===
@app.route("/predict", methods=["POST"])
def predict():
    try:
        data = request.get_json()

        # Always forward to Hugging Face model
        hf_url = "https://sampath563-medica-backend.hf.space/predict"
        response = requests.post(hf_url, json=data)
        return jsonify(response.json()), response.status_code

    except Exception as e:
        print("❌ Hugging Face proxy error:", str(e))
        return jsonify({"error": str(e)}), 500

# === Proxy to Hugging Face for Re-Prediction ===
@app.route("/repredict", methods=["POST"])
def repredict():
    try:
        data = request.get_json()

        # Forward request to Hugging Face /repredict
        hf_url = "https://sampath563-medica-backend.hf.space/repredict"
        response = requests.post(hf_url, json=data)
        return jsonify(response.json()), response.status_code

    except Exception as e:
        print("❌ Hugging Face repredict proxy error:", str(e))
        return jsonify({"error": str(e)}), 500


# === Treatment Plan Generator ===
# === Treatment Endpoint ===
@app.route("/api/treatment", methods=["POST"])
def generate_treatment():
    try:
        

        data = request.get_json(force=True)
        disease = data.get("disease", "").strip()
        symptoms = data.get("symptoms", [])
        age = data.get("age")
        blood_group = data.get("blood_group", "")
        duration = data.get("duration")

        if not disease or not symptoms or not age:
            return jsonify({"error": "Missing required patient information"}), 400

        # Construct prompt for Gemini
        prompt = f"""
You are an AI medical assistant.

Patient Details:
- Disease: {disease}
- Age: {age}
- Blood Group: {blood_group}
- Symptoms: {', '.join(symptoms)}
- Duration: {duration} days

Instructions:
1. Generate exactly 3 medications strictly based on the disease (ignore symptoms).
2. Return a JSON ONLY with the format:
{{
  "medications": ["Medicine1", "Medicine2", "Medicine3"],
  "lifestyle": ["point1", "point2", "point3"],
  "followup": "short sentence about follow-up"
}}
3. Do NOT include any explanations or extra text.
"""

        treatment_data = fetch_gemini_response(prompt)  # Your Gemini fetch function

        # Add intake/timing
        normalized_patterns = {k.lower(): v for k, v in default_patterns.items()}
        for med in treatment_data.get("medications", []):
            med_name_lower = med["name"].lower()
            if med_name_lower in normalized_patterns:
                pattern = normalized_patterns[med_name_lower]
                med["intake"] = pattern.split(' ')[0]
                med["timing"] = ' '.join(pattern.split(' ')[1:])
            else:
                med["intake"] = "1-0-1"
                med["timing"] = "after food"

        full_prescription = {
            "disease": disease,
            "age": age,
            "symptoms": symptoms,
            "blood_group": blood_group,
            "duration": duration,
            "treatment": treatment_data
        }

        return jsonify(full_prescription), 200

    except Exception as e:
        print(f"❌ Treatment endpoint error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/treatment/download", methods=["POST"])
def download_prescription():
    try:
        data = request.get_json(force=True)
        prescription = data  # expects full prescription JSON

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
        y -= 20
        c.drawString(100, y, f"Symptoms: {', '.join(prescription.get('symptoms', []))}")
        y -= 20
        c.drawString(100, y, f"Duration: {prescription.get('duration', '')} days")
        y -= 30

        c.setFont("Helvetica-Bold", 14)
        c.drawString(100, y, "🩺 Medications:")
        y -= 20
        c.setFont("Helvetica", 12)
        for med in prescription.get("treatment", {}).get("medications", []):
            c.drawString(120, y, f"- {med['name']} ({med['intake']}, {med['timing']})")
            y -= 20

        y -= 10
        c.setFont("Helvetica-Bold", 14)
        c.drawString(100, y, "🍎 Lifestyle Recommendations:")
        y -= 20
        c.setFont("Helvetica", 12)
        for life in prescription.get("treatment", {}).get("lifestyle", []):
            c.drawString(120, y, f"- {life}")
            y -= 20

        y -= 10
        c.setFont("Helvetica-Bold", 14)
        c.drawString(100, y, "📅 Follow-up:")
        y -= 20
        c.setFont("Helvetica", 12)
        c.drawString(120, y, prescription.get("treatment", {}).get("followup", ""))

        c.save()

        return send_file(filepath, as_attachment=True)

    except Exception as e:
        print(f"❌ Could not generate PDF: {e}")
        return jsonify({"error": "Could not generate PDF"}), 500

# === Health Check Endpoints ===
@app.route("/api/ping-db", methods=["GET"])
def ping_db():
    try:
        count = users.count_documents({})
        return jsonify({"message": "MongoDB connected ✅", "user_count": count})
    except Exception as e:
        return jsonify({"error": f"MongoDB connection failed: {str(e)}"}), 500

@app.route('/api/feedback', methods=['POST'])
def store_feedback():
    data = request.json
    name = data.get('name')
    email = data.get('email')
    message = data.get('message')
    
    if not name or not email or not message:
        return jsonify({'error': 'Missing fields'}), 400

    feedback_data = {
        'name': name,
        'email': email,
        'message': message,
        'timestamp': datetime.now()
    }
    
    try:
        db.feedback.insert_one(feedback_data)
        return jsonify({'success': True, 'message': 'Feedback submitted successfully'})
    except Exception as e:
        return jsonify({'error': 'Failed to store feedback', 'details': str(e)}), 500

@app.route("/api/submit-feedback", methods=["POST"])
def submit_feedback():
    try:
        data = request.json
        email = data.get("email", "anonymous")
        message = data.get("message", "")
        timestamp = datetime.utcnow()

        if not message:
            return jsonify({"success": False, "message": "Feedback message is required"}), 400

        feedback = {
            "email": email,
            "message": message,
            "timestamp": timestamp
        }

        db.feedback.insert_one(feedback)
        return jsonify({"success": True, "message": "Feedback submitted successfully"}), 200

    except Exception as e:
        print("Error saving feedback:", e)
        return jsonify({"success": False, "message": "Internal Server Error"}), 500

# === Main Entrypoint ===
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
