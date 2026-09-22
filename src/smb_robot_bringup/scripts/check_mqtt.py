import paho.mqtt.client as mqtt
import ssl

# Cấu hình cho EMQX Cloud của bạn
BROKER_URL = "l07702d7.ala.asia-southeast1.emqxsl.com"
PORT = 8883
USERNAME = "Smartmarketbot"
PASSWORD = "Passsep490"

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"✅ Connected successfully to HiveMQ Cloud!")
        print("🎧 Listening for all messages on all topics...")
        client.subscribe("#")
    else:
        print(f"❌ Failed to connect, return code {rc}")

def on_message(client, userdata, msg):
    print(f"[{msg.topic}] {msg.payload.decode('utf-8')}")

client = mqtt.Client()
client.username_pw_set(USERNAME, PASSWORD)
client.tls_set(tls_version=ssl.PROTOCOL_TLS)

client.on_connect = on_connect
client.on_message = on_message

try:
    print(f"Connecting to {BROKER_URL}:{PORT}...")
    client.connect(BROKER_URL, PORT, 60)
    client.loop_forever()
except Exception as e:
    print(f"❌ Failed to connect: {e}")
