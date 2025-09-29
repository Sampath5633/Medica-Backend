import smtplib
from email.message import EmailMessage

# === SMTP Settings from your .env ===
MAIL_SERVER = "smtp.gmail.com"
MAIL_PORT = 587
MAIL_USERNAME = "bsampath563@gmail.com"
MAIL_PASSWORD = "nwycfvqckcpfhztv"  # App password, no spaces

# === Email Content ===
msg = EmailMessage()
msg['Subject'] = "Test Email from MEDICA"
msg['From'] = MAIL_USERNAME
msg['To'] = "bsampath563@gmail.com"  # You can change to another email to test
msg.set_content("✅ This is a test email from your MEDICA backend.")

# === Send Email ===
try:
    with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
        server.starttls()
        server.login(MAIL_USERNAME, MAIL_PASSWORD)
        server.send_message(msg)
    print("✅ Email sent successfully!")
except Exception as e:
    print("❌ Failed to send email:", e)
