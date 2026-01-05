# -*- coding: utf-8 -*-
"""
AgriSense BLE Gateway

Scans for AgriSense ESP32 devices via Bluetooth Low Energy,
receives sensor data, and publishes to local MQTT broker.

Usage:
    python ble_gateway.py

Requirements:
    pip install bleak paho-mqtt
"""

import asyncio
import json
import logging
from datetime import datetime
from bleak import BleakScanner, BleakClient
import paho.mqtt.client as mqtt
import sqlite3

# ============== Configuration ==============

# BLE Settings
DEVICE_NAME_PREFIX = "AgriSense"
SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
DATA_CHAR_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"

# MQTT Settings
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "agrisense/sensors/data"

# Database Settings
DB_FILE = "agrisense_data.db"

# Scan Settings
SCAN_INTERVAL = 5  # seconds between scans

# ============== Logging ==============

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============== MQTT Client ==============

mqtt_client = mqtt.Client()
mqtt_connected = False

def on_mqtt_connect(client, userdata, flags, rc):
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        logger.info("Connected to MQTT broker")
    else:
        logger.error(f"MQTT connection failed: {rc}")

def on_mqtt_disconnect(client, userdata, rc):
    global mqtt_connected
    mqtt_connected = False
    logger.warning("Disconnected from MQTT broker")

mqtt_client.on_connect = on_mqtt_connect
mqtt_client.on_disconnect = on_mqtt_disconnect

# ============== Database ==============

db_connection = None

def init_database():
    """Initialize SQLite database and create table if not exists"""
    global db_connection
    try:
        db_connection = sqlite3.connect(DB_FILE, check_same_thread=False)
        cursor = db_connection.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sensor_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                node_id TEXT,
                location TEXT,
                temperature REAL,
                humidity REAL,
                soil REAL,
                soil_raw INTEGER,
                light REAL,
                light_raw INTEGER,
                air_quality REAL,
                air_raw INTEGER,
                received_at TEXT
            )
        ''')

        db_connection.commit()
        logger.info(f"Database initialized: {DB_FILE}")

    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

def save_to_database(sensor_data):
    """Save sensor data to SQLite database"""
    if db_connection is None:
        logger.warning("Database not initialized - data not saved")
        return

    try:
        cursor = db_connection.cursor()

        cursor.execute('''
            INSERT INTO sensor_readings (
                timestamp, node_id, location, temperature, humidity,
                soil, soil_raw, light, light_raw, air_quality, air_raw, received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            sensor_data.get('node_id'),
            sensor_data.get('location'),
            sensor_data.get('temperature'),
            sensor_data.get('humidity'),
            sensor_data.get('soil'),
            sensor_data.get('soil_raw'),
            sensor_data.get('light'),
            sensor_data.get('light_raw'),
            sensor_data.get('air_quality'),
            sensor_data.get('air_raw'),
            sensor_data.get('received_at')
        ))

        db_connection.commit()

    except Exception as e:
        logger.error(f"Failed to save to database: {e}")

# ============== BLE Gateway ==============

connected_devices = {}

async def notification_handler(sender, data):
    """Handle incoming BLE notifications"""
    try:
        payload = data.decode('utf-8')
        sensor_data = json.loads(payload)
        
        # Add timestamp
        sensor_data['received_at'] = datetime.now().isoformat()
        
        # Flatten nested data if present
        if 'data' in sensor_data:
            for key, value in sensor_data['data'].items():
                sensor_data[key] = value
            del sensor_data['data']

        # Save to SQLite database immediately
        save_to_database(sensor_data)

        # Publish to MQTT
        if mqtt_connected:
            mqtt_client.publish(MQTT_TOPIC, json.dumps(sensor_data))
            logger.info(f"Published: {sensor_data.get('node_id', 'unknown')} - "
                       f"Temp: {sensor_data.get('temperature', 'N/A')}°C, "
                       f"Humidity: {sensor_data.get('humidity', 'N/A')}%, "
                       f"Soil: {sensor_data.get('soil', 'N/A')}%, "
                       f"Light: {sensor_data.get('light', 'N/A')}%")
        else:
            logger.warning("MQTT not connected - data not published")
            
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON: {e}")
    except Exception as e:
        logger.error(f"Error handling notification: {e}")

async def connect_device(device):
    """Connect to a discovered AgriSense device"""
    if device.address in connected_devices:
        return
    
    logger.info(f"Connecting to {device.name} ({device.address})...")
    
    try:
        client = BleakClient(device.address)
        await client.connect()
        
        if client.is_connected:
            logger.info(f"Connected to {device.name}")
            connected_devices[device.address] = client
            
            # Subscribe to notifications
            await client.start_notify(DATA_CHAR_UUID, notification_handler)
            logger.info(f"Subscribed to notifications from {device.name}")
            
    except Exception as e:
        logger.error(f"Failed to connect to {device.name}: {e}")

async def scan_and_connect():
    """Scan for devices and connect"""
    logger.info("Scanning for AgriSense devices...")
    
    devices = await BleakScanner.discover(timeout=5.0)
    
    for device in devices:
        if device.name and device.name.startswith(DEVICE_NAME_PREFIX):
            await connect_device(device)

async def monitor_connections():
    """Monitor and reconnect dropped connections"""
    while True:
        # Check connected devices
        disconnected = []
        for address, client in connected_devices.items():
            if not client.is_connected:
                disconnected.append(address)
        
        # Remove disconnected devices
        for address in disconnected:
            logger.warning(f"Device {address} disconnected")
            del connected_devices[address]
        
        # Scan for new devices
        await scan_and_connect()
        
        await asyncio.sleep(SCAN_INTERVAL)

async def main():
    """Main entry point"""
    logger.info("=" * 50)
    logger.info("  AgriSense BLE Gateway")
    logger.info("=" * 50)
    logger.info(f"  MQTT Broker: {MQTT_BROKER}:{MQTT_PORT}")
    logger.info(f"  MQTT Topic:  {MQTT_TOPIC}")
    logger.info(f"  Database:    {DB_FILE}")
    logger.info("=" * 50)

    # Initialize database
    init_database()

    # Connect to MQTT
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
    except Exception as e:
        logger.error(f"Failed to connect to MQTT: {e}")
        return
    
    # Run BLE monitoring
    try:
        await monitor_connections()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        # Disconnect all devices
        for address, client in connected_devices.items():
            try:
                await client.disconnect()
            except:
                pass

        # Close database connection
        if db_connection:
            db_connection.close()
            logger.info("Database connection closed")

        mqtt_client.loop_stop()
        mqtt_client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
