import os
import requests
import random
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_mail import Mail, Message
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
import jwt

from medication_patterns import default_patterns
from your_gemini_util import fetch_gemini_response 

# Temporary storage for prescriptions (you may replace with DB)
# This is currently unused, but keeping it in case it's for future use.
PRESCRIPTIONS = {}

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


# === MongoDB Setup ===
mongo_uri = os.getenv("MONGO_URI")
client = MongoClient(mongo_uri)
db = client["medicalDB"]
users_collection = db["users"]
feedback_collection = db["feedbacks"]   

# === Utility: Send Email ===
def generate_jwt(email):
    payload = {"email": email, "exp": datetime.utcnow() + timedelta(hours=2)}
    token = jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")
    return token

def generate_code():
    return str(random.randint(100000, 999999))

# === Utility function for sending emails ===
# === Utility function for sending emails via SendGrid API ===
def send_email(subject, recipient, body):
    import os
    import requests

    try:
        url = "https://api.sendgrid.com/v3/mail/send"
        headers = {
            "Authorization": f"Bearer {os.getenv('SENDGRID_API_KEY')}",
            "Content-Type": "application/json"
        }
        data = {
            "personalizations": [{
                "to": [{"email": recipient}],
                "subject": subject
            }],
            "from": {"email": os.getenv("FROM_EMAIL")},
            "content": [{
                "type": "text/plain",
                "value": body
            }]
        }
        response = requests.post(url, headers=headers, json=data)
        if response.status_code in [200, 202]:
            print(f"✅ Email sent to {recipient}")
            return True
        else:
            print(f"❌ Email send failed: {response.status_code}, {response.text}")
            return False
    except Exception as e:
        print("❌ SendGrid email error:", e)
        return False


# === Send Verification Code ===
@app.route("/api/send-verification-code", methods=["POST"])
def send_verification_code():
    data = request.json
    user_email = data.get("email")
    if not isinstance(user_email, str) or not user_email.strip():
        return jsonify({"error": "Email is required"}), 400

    code = generate_code()
    users_collection.update_one(
        {"email": user_email},
        {"$set": {"verification_code": code, "code_expiry": datetime.utcnow() + timedelta(minutes=10)}},
        upsert=True
    )

    if send_email("🔐 Your Verification Code", user_email, f"Your verification code is {code}. It will expire in 10 minutes."):
        return jsonify({"message": "Verification code sent successfully"})
    else:
        return jsonify({"error": "Failed to send verification code"}), 500

# === Register ===
@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(force=True)
    email = data.get("email")
    password = data.get("password")

    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify({"message": "Missing or invalid email/password"}), 400

    if users_collection.find_one({"email": email}):
        return jsonify({"message": "User already exists"}), 400

    hashed_password = generate_password_hash(password)
    users_collection.insert_one({
        "email": email,
        "password": hashed_password,
        "is_verified": False
    })
    return jsonify({"message": "Registration successful"}), 201

# === Login Step 1 ===
@app.route("/api/login-step1", methods=["POST"])
def login_step1():
    try:
        data = request.get_json(force=True)
        email = data.get("email")
        password = data.get("password")

        if not isinstance(email, str) or not isinstance(password, str):
            return jsonify({"message": "Email and password must be strings"}), 400

        user = users_collection.find_one({"email": email})
        if not user:
            return jsonify({"message": "User not found"}), 401

        stored_password = user.get("password")
        if not isinstance(stored_password, str):
            return jsonify({"message": "Invalid credentials"}), 401

        if not check_password_hash(stored_password, password):
            return jsonify({"message": "Invalid credentials"}), 401

        if user.get("is_verified", False):
            token = generate_jwt(email)
            return jsonify({"token": token}), 200

        # Send verification code
        code = generate_code()
        users_collection.update_one(
            {"email": email},
            {"$set": {"verification_code": code, "code_expiry": datetime.utcnow() + timedelta(minutes=10)}}
        )
        send_email("Your MEDICA Verification Code", email, f"Your verification code is: {code}")
        return jsonify({"step": 2}), 200
    except Exception as e:
        print("Error in login-step1:", e)
        return jsonify({"message": "Internal Server Error"}), 500

# === Login Step 2 ===
@app.route("/api/login-step2", methods=["POST"])
def login_step2():
    try:
        data = request.get_json(force=True)
        email = data.get("email")
        code = data.get("code")

        if not isinstance(email, str) or not isinstance(code, str):
            return jsonify({"message": "Email and code must be strings"}), 400

        user = users_collection.find_one({"email": email})
        if not user:
            return jsonify({"message": "User not found"}), 404

        if user.get("is_verified", False):
            token = generate_jwt(email)
            return jsonify({"message": "Already verified", "token": token}), 200

        if user.get("verification_code") != code:
            return jsonify({"message": "Invalid verification code"}), 401

        if datetime.utcnow() > user.get("code_expiry", datetime.utcnow()):
            return jsonify({"message": "Code expired"}), 401

        users_collection.update_one(
            {"email": email},
            {"$unset": {"verification_code": "", "code_expiry": ""},
             "$set": {"is_verified": True}}
        )
        token = generate_jwt(email)
        return jsonify({"message": "Login successful", "token": token}), 200
    except Exception as e:
        print("Error in login-step2:", e)
        return jsonify({"message": "Login step 2 failed", "error": str(e)}), 500

# === Send Reset Code ===
@app.route("/api/send-reset-code", methods=["POST"])
def send_reset_code():
    try:
        data = request.get_json(force=True)
        email = data.get("email")
        if not isinstance(email, str):
            return jsonify({"message": "Invalid email"}), 400

        user = users_collection.find_one({"email": email})
        if not user:
            return jsonify({"message": "User not found"}), 404

        code = generate_code()
        users_collection.update_one(
            {"email": email},
            {"$set": {"reset_code": code, "reset_expiry": datetime.utcnow() + timedelta(minutes=10)}}
        )
        send_email("MEDICA Password Reset Code", email, f"Your password reset code is: {code}")
        return jsonify({"message": "Reset code sent"}), 200
    except Exception as e:
        print("Error in send-reset-code:", e)
        return jsonify({"message": "Internal Server Error"}), 500

# === Reset Password ===
@app.route("/api/reset-password", methods=["POST"])
def reset_password():
    try:
        data = request.get_json(force=True)
        email = data.get("email")
        code = data.get("code")
        new_password = data.get("newPassword")

        if not all(isinstance(x, str) for x in [email, code, new_password]):
            return jsonify({"message": "Invalid input"}), 400

        user = users_collection.find_one({"email": email})
        if not user:
            return jsonify({"message": "User not found"}), 404

        if user.get("reset_code") != code:
            return jsonify({"message": "Invalid reset code"}), 401

        if datetime.utcnow() > user.get("reset_expiry", datetime.utcnow()):
            return jsonify({"message": "Reset code expired"}), 401

        hashed_password = generate_password_hash(new_password)
        users_collection.update_one(
            {"email": email},
            {"$set": {"password": hashed_password},
             "$unset": {"reset_code": "", "reset_expiry": ""}}
        )
        return jsonify({"message": "Password reset successful"}), 200
    except Exception as e:
        print("Error in reset-password:", e)
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
        

        data = request.get_json()
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
        data = request.get_json()
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
        count = users_collection.count_documents({})
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
        feedback_collection.insert_one(feedback_data)
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

        feedback_collection.insert_one(feedback)
        return jsonify({"success": True, "message": "Feedback submitted successfully"}), 200

    except Exception as e:
        print("Error saving feedback:", e)
        return jsonify({"success": False, "message": "Internal Server Error"}), 500

# === Main Entrypoint ===
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
