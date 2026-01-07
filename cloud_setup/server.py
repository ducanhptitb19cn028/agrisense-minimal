nano mqtt_worker.py

import json
import psycopg2
import paho.mqtt.client as mqtt
from datetime import datetime

# --- CONFIGURATION ---
MQTT_HOST = "51.107.8.227"
MQTT_PORT = 1883
MQTT_TOPIC_SENSORS = "agrisense/sensors/data"
MQTT_TOPIC_ALARM = "agrisense/alarms"

DB_CONFIG = {
    "dbname": "agrisensedb", 
    "user": "admin",
    "password": "agrisense",
    "host": "localhost",
    "port": "5432"
}

# --- DATABASE FUNCTION ---
def save_to_db(data):
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # 1. Extract Datas
        node_id = data.get("node_id", "unknown_device")
        location = data.get("location", "unknown_location")
        timestamp = data.get("received_at", datetime.now().isoformat())
        edge_id = data.get("edge_id", "unknown_edge_id")
        edge_name = data.get("edge_name", "unknown_edge_name")
        edge_location = data.get("edge_location", "unknown_edge_location")
        
        # 2. Extract metrics to ignore (metadata)
        ignore_keys = ['node_id', 'location', 'received_at', 'edge_id', 'edge_name', 'edge_location']
        
        # 3. Loop through the remaining keys (temperature, humidity, etc.)   
        for key, value in data.items():
            if key not in ignore_keys and value is not None and value != "N/A":
                query = """
                    INSERT INTO tagrisense (node_id, location, timestamp, edge_id, edge_name, edge_location, metric, value)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(query, (node_id, location, timestamp, edge_id, edge_name, edge_location, key, value))
        
        conn.commit()
        print(f"[{datetime.now()}] Saved data from {node_id}")
        cursor.close()
        
    except Exception as e:
        print(f"Database Error: {e}")
    finally:
        if conn is not None:
            conn.close()

# --- MQTT HANDLERS ---
def on_connect(client, userdata, flags, rc):
    print(f"Connected to MQTT Broker (Code: {rc})")
    # Subscribe to both topics
    client.subscribe(MQTT_TOPIC_SENSORS)
    client.subscribe(MQTT_TOPIC_ALARM)
    print(f"Subscribed to: {MQTT_TOPIC_SENSORS} and {MQTT_TOPIC_ALARM}")

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode('utf-8')
        
        # Route logic based on the topic
        if msg.topic == MQTT_TOPIC_ALARM:
            print("\n" + "="*30)
            print(f"ALARM RECEIVED: {payload}")
            print("="*30 + "\n")
        
        elif msg.topic == MQTT_TOPIC_SENSORS:
            data = json.loads(payload)
            save_to_db(data)
            
    except Exception as e:
        print(f"Error processing message on {msg.topic}: {e}")

# --- MAIN LOOP ---
if __name__ == "__main__":
    # Install paho-mqtt if missing: pip install paho-mqtt
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    print("Starting MQTT Worker...")
    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.loop_forever() # Runs forever blocking this script
    except KeyboardInterrupt:
        print("Stopping...")
        client.disconnect()
