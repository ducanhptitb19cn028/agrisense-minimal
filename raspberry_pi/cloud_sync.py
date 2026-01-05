# -*- coding: utf-8 -*-
"""
AgriSense Cloud Sync Service

Asynchronous data synchronisation between Raspberry Pi (Edge) and OpenStack (Cloud).
Subscribes to local MQTT broker and forwards sensor data to cloud MQTT broker.

Architecture:
    ┌─────────────────┐         ┌─────────────────┐
    │  Raspberry Pi   │  MQTT   │    OpenStack    │
    │     (Edge)      │────────►│     (Cloud)     │
    │                 │         │                 │
    │  Local MQTT     │         │  Cloud MQTT     │
    │  (localhost)    │         │  (51.107.x.x)   │
    └─────────────────┘         └─────────────────┘

Data Flow:
    ESP32 → BLE → ble_gateway.py → Local MQTT → cloud_sync.py → Cloud MQTT
                                       ↓
                                   Node-RED (Alarms)

Usage:
    python cloud_sync.py

Requirements:
    pip install paho-mqtt
"""

import paho.mqtt.client as mqtt
import json
import logging
import time
import sqlite3
import os
from datetime import datetime
from threading import Thread, Lock
from queue import Queue
import argparse

# ============== Configuration ==============

class Config:
    # Local MQTT Broker (Raspberry Pi)
    LOCAL_BROKER = "localhost"
    LOCAL_PORT = 1883
    LOCAL_TOPIC = "agrisense/sensors/data"
    
    # Cloud MQTT Broker (OpenStack)
    CLOUD_BROKER = "172.22.249.96"  # Your OpenStack server IP
    CLOUD_PORT = 1883
    CLOUD_TOPIC = "agrisense/sensors/data"
    CLOUD_ALARMS_TOPIC = "agrisense/alarms"
    
    # Sync settings
    REALTIME_MODE = True      # Send data immediately (True) or use batching (False)
    BATCH_SIZE = 1            # Number of readings to batch before sending (1 for real-time)
    BATCH_TIMEOUT = 2         # Send batch after this many seconds even if not full
    RETRY_INTERVAL = 5        # Seconds between reconnection attempts
    OFFLINE_DB = "offline_queue.db"

    # Edge identity
    EDGE_ID = "edge-rpi-001"
    EDGE_NAME = "AgriSense Gateway"
    EDGE_LOCATION = "Greenhouse-A"


# ============== Logging Setup ==============

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============== Offline Queue (SQLite) ==============

class OfflineQueue:
    """
    SQLite-based queue for storing readings when cloud is unreachable.
    Ensures no data loss during network outages.
    """
    
    def __init__(self, db_path: str = Config.OFFLINE_DB):
        self.db_path = db_path
        self._init_db()
        self._lock = Lock()
    
    def _init_db(self):
        """Initialise SQLite database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reading_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending'
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info(f"Offline queue initialised: {self.db_path}")
    
    def enqueue(self, data: dict) -> int:
        """Add reading to offline queue"""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute(
                'INSERT INTO reading_queue (data) VALUES (?)',
                (json.dumps(data),)
            )
            
            queue_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            return queue_id
    
    def get_pending(self, limit: int = 100) -> list:
        """Get pending readings"""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, data FROM reading_queue 
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT ?
            ''', (limit,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'id': row[0],
                    'data': json.loads(row[1])
                })
            
            conn.close()
            return results
    
    def mark_sent(self, ids: list):
        """Mark readings as sent"""
        if not ids:
            return
            
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            placeholders = ','.join('?' * len(ids))
            cursor.execute(f'''
                DELETE FROM reading_queue WHERE id IN ({placeholders})
            ''', ids)
            
            conn.commit()
            conn.close()
    
    def get_count(self) -> int:
        """Get number of pending readings"""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM reading_queue WHERE status = "pending"')
            count = cursor.fetchone()[0]
            
            conn.close()
            return count


# ============== Cloud Sync Service ==============

class CloudSyncService:
    """
    Handles bidirectional MQTT sync between edge and cloud.
    """
    
    def __init__(self, config: Config = Config):
        self.config = config
        self.offline_queue = OfflineQueue()
        
        # MQTT clients
        self.local_client = None
        self.cloud_client = None
        
        # State
        self.cloud_connected = False
        self.local_connected = False
        self.running = False
        
        # Batch buffer
        self.batch_buffer = []
        self.batch_lock = Lock()
        self.last_batch_time = time.time()
        
        # Statistics
        self.stats = {
            'readings_received': 0,
            'readings_sent': 0,
            'readings_queued': 0,
            'connection_errors': 0,
            'last_sync': None
        }
    
    def start(self):
        """Start the sync service"""
        self.running = True

        # Setup local MQTT client
        self._setup_local_client()

        # Setup cloud MQTT client
        self._setup_cloud_client()

        # Start batch sender thread
        batch_thread = Thread(target=self._batch_sender_loop, daemon=True)
        batch_thread.start()

        # Start offline queue processor thread
        queue_thread = Thread(target=self._offline_queue_processor, daemon=True)
        queue_thread.start()

        # Start statistics reporter thread
        stats_thread = Thread(target=self._stats_reporter_loop, daemon=True)
        stats_thread.start()

        logger.info("Cloud sync service started")
        logger.info(f"  Local broker: {self.config.LOCAL_BROKER}:{self.config.LOCAL_PORT}")
        logger.info(f"  Cloud broker: {self.config.CLOUD_BROKER}:{self.config.CLOUD_PORT}")
        
        # Connect clients
        try:
            self.local_client.connect(self.config.LOCAL_BROKER, self.config.LOCAL_PORT, 60)
            self.local_client.loop_start()
        except Exception as e:
            logger.error(f"Failed to connect to local broker: {e}")
        
        try:
            self.cloud_client.connect(self.config.CLOUD_BROKER, self.config.CLOUD_PORT, 60)
            self.cloud_client.loop_start()
        except Exception as e:
            logger.error(f"Failed to connect to cloud broker: {e}")
            self.stats['connection_errors'] += 1
        
        # Keep running
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
    
    def stop(self):
        """Stop the sync service"""
        self.running = False
        
        if self.local_client:
            self.local_client.loop_stop()
            self.local_client.disconnect()
        
        if self.cloud_client:
            self.cloud_client.loop_stop()
            self.cloud_client.disconnect()
        
        logger.info("Cloud sync service stopped")
    
    def _setup_local_client(self):
        """Setup local MQTT client"""
        self.local_client = mqtt.Client(client_id="cloud_sync_local")
        
        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                self.local_connected = True
                logger.info("Connected to local MQTT broker")
                # Subscribe to ALL sensor data from ESP32 (via BLE gateway)
                client.subscribe(self.config.LOCAL_TOPIC)
                logger.info(f"  Subscribed to: {self.config.LOCAL_TOPIC} (ESP32 sensor data)")
                # Also subscribe to alarms to forward them
                client.subscribe("agrisense/alarms")
                logger.info(f"  Subscribed to: agrisense/alarms (Node-RED alarms)")
            else:
                logger.error(f"Local MQTT connection failed: {rc}")
        
        def on_disconnect(client, userdata, rc):
            self.local_connected = False
            logger.warning("Disconnected from local MQTT broker")
        
        def on_message(client, userdata, msg):
            self._handle_local_message(msg)
        
        self.local_client.on_connect = on_connect
        self.local_client.on_disconnect = on_disconnect
        self.local_client.on_message = on_message
    
    def _setup_cloud_client(self):
        """Setup cloud MQTT client"""
        self.cloud_client = mqtt.Client(client_id=f"edge_{self.config.EDGE_ID}")
        
        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                self.cloud_connected = True
                logger.info("Connected to cloud MQTT broker")
                # Subscribe to commands from cloud (optional)
                client.subscribe(f"agrisense/commands/{self.config.EDGE_ID}")
            else:
                logger.error(f"Cloud MQTT connection failed: {rc}")
                self.stats['connection_errors'] += 1
        
        def on_disconnect(client, userdata, rc):
            self.cloud_connected = False
            logger.warning("Disconnected from cloud MQTT broker")
        
        def on_message(client, userdata, msg):
            self._handle_cloud_message(msg)
        
        self.cloud_client.on_connect = on_connect
        self.cloud_client.on_disconnect = on_disconnect
        self.cloud_client.on_message = on_message
    
    def _handle_local_message(self, msg):
        """Handle message from local MQTT broker"""
        try:
            # Receive COMPLETE sensor payload from ESP32 (via BLE gateway)
            # Contains: node_id, location, temperature, humidity,
            #           light, light_raw, soil, soil_raw, air_quality, air_raw
            payload = json.loads(msg.payload.decode())
            self.stats['readings_received'] += 1

            # Add edge metadata (preserves ALL original sensor fields)
            payload['edge_id'] = self.config.EDGE_ID
            payload['edge_name'] = self.config.EDGE_NAME
            payload['edge_location'] = self.config.EDGE_LOCATION
            payload['received_at'] = datetime.now().isoformat()

            if msg.topic == "agrisense/alarms":
                # Forward alarms immediately (always real-time)
                success = self._send_to_cloud(self.config.CLOUD_ALARMS_TOPIC, payload)
                if success:
                    logger.warning(f"ALARM sent to cloud: {payload.get('violations', 'unknown')}")
                else:
                    logger.error(f"ALARM queued (cloud offline): {payload.get('violations', 'unknown')}")
            else:
                # In real-time mode, send immediately; otherwise batch
                if self.config.REALTIME_MODE:
                    # Send ALL sensor data immediately to cloud (no filtering)
                    success = self._send_to_cloud(self.config.CLOUD_TOPIC, payload)
                    if success:
                        logger.info(f"Sent ALL sensor data to cloud from {payload.get('node_id', 'unknown')}:")
                        logger.info(f"    Temp: {payload.get('temperature', 'N/A')}°C, "
                                   f"Humidity: {payload.get('humidity', 'N/A')}%")
                        logger.info(f"    Light: {payload.get('light', 'N/A')}% (raw: {payload.get('light_raw', 'N/A')}), "
                                   f"Soil: {payload.get('soil', 'N/A')}% (raw: {payload.get('soil_raw', 'N/A')})")
                        logger.info(f"    Air Quality: {payload.get('air_quality', 'N/A')} (raw: {payload.get('air_raw', 'N/A')})")
                    else:
                        logger.warning(f"Queued (cloud offline): {payload.get('node_id', 'unknown')} - "
                                      f"Queue size: {self.offline_queue.get_count()}")
                else:
                    # Add sensor data to batch
                    with self.batch_lock:
                        self.batch_buffer.append(payload)

                    logger.debug(f"Buffered reading from {payload.get('node_id', 'unknown')}")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from local broker: {e}")
        except Exception as e:
            logger.error(f"Error handling local message: {e}")
    
    def _handle_cloud_message(self, msg):
        """Handle message from cloud MQTT broker (commands)"""
        try:
            payload = json.loads(msg.payload.decode())
            logger.info(f"Received command from cloud: {payload}")
            
            # Forward command to local MQTT for Node-RED/actuators
            if self.local_connected:
                self.local_client.publish(
                    "agrisense/commands",
                    json.dumps(payload)
                )
                
        except Exception as e:
            logger.error(f"Error handling cloud message: {e}")
    
    def _send_to_cloud(self, topic: str, payload: dict) -> bool:
        """
        Send COMPLETE sensor data to cloud MQTT broker.

        Sends entire payload with ALL sensor fields (no filtering):
        - All ESP32 sensor data: temperature, humidity, light, light_raw,
          soil, soil_raw, air_quality, air_raw, node_id, location
        - Edge metadata: edge_id, edge_name, edge_location, received_at
        """
        if not self.cloud_connected:
            # Queue for later
            self.offline_queue.enqueue({'topic': topic, 'payload': payload})
            self.stats['readings_queued'] += 1
            logger.warning("Cloud offline - queued reading")
            return False

        try:
            # Send ENTIRE payload as JSON (all sensor fields included)
            result = self.cloud_client.publish(
                topic,
                json.dumps(payload),  # Serializes ALL fields in payload
                qos=1  # At least once delivery
            )
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self.stats['readings_sent'] += 1
                self.stats['last_sync'] = datetime.now().isoformat()
                return True
            else:
                # Queue for retry
                self.offline_queue.enqueue({'topic': topic, 'payload': payload})
                self.stats['readings_queued'] += 1
                return False
                
        except Exception as e:
            logger.error(f"Error sending to cloud: {e}")
            self.offline_queue.enqueue({'topic': topic, 'payload': payload})
            self.stats['readings_queued'] += 1
            return False
    
    def _batch_sender_loop(self):
        """Periodically send batched readings to cloud"""
        while self.running:
            time.sleep(1)
            
            should_send = False
            
            with self.batch_lock:
                # Send if batch is full
                if len(self.batch_buffer) >= self.config.BATCH_SIZE:
                    should_send = True
                # Or if timeout reached and buffer not empty
                elif len(self.batch_buffer) > 0:
                    if time.time() - self.last_batch_time >= self.config.BATCH_TIMEOUT:
                        should_send = True
            
            if should_send:
                self._send_batch()
    
    def _send_batch(self):
        """Send current batch to cloud"""
        with self.batch_lock:
            if not self.batch_buffer:
                return
            
            batch = self.batch_buffer.copy()
            self.batch_buffer.clear()
            self.last_batch_time = time.time()
        
        # Create batch payload
        batch_payload = {
            'edge_id': self.config.EDGE_ID,
            'edge_name': self.config.EDGE_NAME,
            'batch_size': len(batch),
            'batch_time': datetime.now().isoformat(),
            'readings': batch
        }
        
        success = self._send_to_cloud(self.config.CLOUD_TOPIC, batch_payload)
        
        if success:
            logger.info(f"Sent batch of {len(batch)} readings to cloud")
        else:
            logger.warning(f"Failed to send batch - queued {len(batch)} readings")
    
    def _offline_queue_processor(self):
        """Process offline queue when cloud becomes available"""
        while self.running:
            time.sleep(self.config.RETRY_INTERVAL)
            
            if not self.cloud_connected:
                continue
            
            pending = self.offline_queue.get_pending(limit=50)
            
            if not pending:
                continue
            
            logger.info(f"Processing {len(pending)} queued readings...")
            
            sent_ids = []
            for item in pending:
                try:
                    topic = item['data'].get('topic', self.config.CLOUD_TOPIC)
                    payload = item['data'].get('payload', item['data'])
                    
                    result = self.cloud_client.publish(
                        topic,
                        json.dumps(payload),
                        qos=1
                    )
                    
                    if result.rc == mqtt.MQTT_ERR_SUCCESS:
                        sent_ids.append(item['id'])
                        self.stats['readings_sent'] += 1
                    
                except Exception as e:
                    logger.error(f"Error processing queued item: {e}")
                    break  # Stop on error, retry later
            
            if sent_ids:
                self.offline_queue.mark_sent(sent_ids)
                logger.info(f"Cleared {len(sent_ids)} readings from offline queue")

    def _stats_reporter_loop(self):
        """Periodically report statistics to confirm data is flowing"""
        report_interval = 60  # Report every 60 seconds
        while self.running:
            time.sleep(report_interval)

            if self.stats['readings_received'] > 0 or self.stats['readings_sent'] > 0:
                queue_size = self.offline_queue.get_count()
                logger.info(f"=== Data Flow Stats ===")
                logger.info(f"  Received from ESP32: {self.stats['readings_received']}")
                logger.info(f"  Sent to cloud: {self.stats['readings_sent']}")
                logger.info(f"  Queued (offline): {self.stats['readings_queued']}")
                logger.info(f"  Queue size: {queue_size}")
                logger.info(f"  Cloud connected: {self.cloud_connected}")
                if self.stats['readings_received'] > 0:
                    success_rate = (self.stats['readings_sent'] / self.stats['readings_received']) * 100
                    logger.info(f"  Success rate: {success_rate:.1f}%")

    def get_status(self) -> dict:
        """Get service status"""
        return {
            'running': self.running,
            'local_connected': self.local_connected,
            'cloud_connected': self.cloud_connected,
            'batch_buffer_size': len(self.batch_buffer),
            'offline_queue_size': self.offline_queue.get_count(),
            'stats': self.stats,
            'config': {
                'edge_id': self.config.EDGE_ID,
                'local_broker': f"{self.config.LOCAL_BROKER}:{self.config.LOCAL_PORT}",
                'cloud_broker': f"{self.config.CLOUD_BROKER}:{self.config.CLOUD_PORT}",
                'realtime_mode': self.config.REALTIME_MODE,
                'batch_size': self.config.BATCH_SIZE,
                'batch_timeout': self.config.BATCH_TIMEOUT
            }
        }


# ============== CLI ==============

def main():
    parser = argparse.ArgumentParser(
        description='AgriSense Cloud Sync Service',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cloud_sync.py                          # Start with default settings (real-time mode)
  python cloud_sync.py --cloud-ip 51.107.8.227  # Specify cloud server IP
  python cloud_sync.py --edge-id greenhouse-01  # Set edge identifier
  python cloud_sync.py --realtime               # Enable real-time sync (default)
  python cloud_sync.py --no-realtime --batch-size 10 --batch-timeout 30  # Use batching
  python cloud_sync.py --test                   # Test cloud connection
        """
    )
    
    parser.add_argument('--cloud-ip', type=str, default=Config.CLOUD_BROKER,
                        help='OpenStack cloud MQTT broker IP')
    parser.add_argument('--cloud-port', type=int, default=Config.CLOUD_PORT,
                        help='Cloud MQTT broker port')
    parser.add_argument('--local-ip', type=str, default=Config.LOCAL_BROKER,
                        help='Local MQTT broker IP')
    parser.add_argument('--local-port', type=int, default=Config.LOCAL_PORT,
                        help='Local MQTT broker port')
    parser.add_argument('--edge-id', type=str, default=Config.EDGE_ID,
                        help='Edge gateway identifier')
    parser.add_argument('--edge-name', type=str, default=Config.EDGE_NAME,
                        help='Edge gateway name')
    parser.add_argument('--batch-size', type=int, default=Config.BATCH_SIZE,
                        help='Number of readings per batch')
    parser.add_argument('--batch-timeout', type=int, default=Config.BATCH_TIMEOUT,
                        help='Send batch after this many seconds')
    parser.add_argument('--realtime', action='store_true', default=Config.REALTIME_MODE,
                        help='Enable real-time mode (send data immediately)')
    parser.add_argument('--no-realtime', dest='realtime', action='store_false',
                        help='Disable real-time mode (use batching)')
    parser.add_argument('--test', action='store_true',
                        help='Test cloud connection and exit')

    args = parser.parse_args()

    # Update config
    Config.CLOUD_BROKER = args.cloud_ip
    Config.CLOUD_PORT = args.cloud_port
    Config.LOCAL_BROKER = args.local_ip
    Config.LOCAL_PORT = args.local_port
    Config.EDGE_ID = args.edge_id
    Config.EDGE_NAME = args.edge_name
    Config.BATCH_SIZE = args.batch_size
    Config.BATCH_TIMEOUT = args.batch_timeout
    Config.REALTIME_MODE = args.realtime
    
    if args.test:
        # Test cloud connection
        print(f"Testing connection to cloud MQTT broker...")
        print(f"  Server: {Config.CLOUD_BROKER}:{Config.CLOUD_PORT}")
        
        test_client = mqtt.Client()
        
        connected = False
        def on_connect(client, userdata, flags, rc):
            nonlocal connected
            if rc == 0:
                connected = True
        
        test_client.on_connect = on_connect
        
        try:
            test_client.connect(Config.CLOUD_BROKER, Config.CLOUD_PORT, 10)
            test_client.loop_start()
            
            # Wait for connection
            for _ in range(10):
                if connected:
                    break
                time.sleep(0.5)
            
            if connected:
                # Send test message
                payload = {
                    'node_id': 'connection_test',
                    'edge_id': Config.EDGE_ID,
                    'message': 'Cloud sync test',
                    'timestamp': datetime.now().isoformat()
                }
                
                result = test_client.publish(
                    Config.CLOUD_TOPIC,
                    json.dumps(payload),
                    qos=1
                )
                
                time.sleep(1)
                
                print(f"Connected successfully!")
                print(f"Test message sent to topic: {Config.CLOUD_TOPIC}")
            else:
                print(f"Connection failed - check IP and firewall")
            
            test_client.loop_stop()
            test_client.disconnect()
            
        except Exception as e:
            print(f"Connection error: {e}")
            print(f"  Check that the server IP is correct and firewall allows port 1883")
        
        return
    
    # Start sync service
    print("=" * 60)
    print("  AgriSense Cloud Sync Service")
    print("=" * 60)
    print(f"  Edge ID:      {Config.EDGE_ID}")
    print(f"  Edge Name:    {Config.EDGE_NAME}")
    print(f"  Local MQTT:   {Config.LOCAL_BROKER}:{Config.LOCAL_PORT}")
    print(f"  Cloud MQTT:   {Config.CLOUD_BROKER}:{Config.CLOUD_PORT}")
    print(f"  Sync Mode:    {'REAL-TIME (immediate)' if Config.REALTIME_MODE else f'BATCH (size: {Config.BATCH_SIZE}, timeout: {Config.BATCH_TIMEOUT}s)'}")
    print("=" * 60)
    print("  Press Ctrl+C to stop")
    print("=" * 60)
    print()
    
    service = CloudSyncService()
    service.start()


if __name__ == '__main__':
    main()
