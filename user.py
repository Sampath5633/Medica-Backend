import smtplib
from email.mime.text import MIMEText
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")  # App Password, no spaces

try:
    # Connect to SMTP server
    server = smtplib.SMTP(MAIL_SERVER, MAIL_PORT)
    server.ehlo()
    server.starttls()
    server.ehlo()
    server.login(MAIL_USERNAME, MAIL_PASSWORD)

    # Create test email
    msg = MIMEText("This is a test email from Medica backend")
    msg["Subject"] = "Test Email"
    msg["From"] = MAIL_USERNAME
    msg["To"] = MAIL_USERNAME

    # Send email
    server.send_message(msg)
    server.quit()
    print("✅ Email sent successfully!")

except Exception as e:
    print("❌ Failed to send email:", e)
