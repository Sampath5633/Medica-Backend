import socket

host = "smtp.gmail.com"
port = 587  # TLS port

try:
    server = socket.create_connection((host, port), timeout=10)
    print("✅ Connection successful!")
    server.close()
except Exception as e:
    print("❌ Connection failed:", e)
