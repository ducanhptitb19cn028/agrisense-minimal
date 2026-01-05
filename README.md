# AgriSense Minimal - IoT Smart Agriculture System

A simplified IoT system for environmental monitoring using ESP32, Raspberry Pi, and OpenStack Cloud.

## System Architecture

```
┌─────────────────┐      BLE       ┌─────────────────┐      MQTT       ┌─────────────────┐
│     ESP32       │ ──────────────►│  Raspberry Pi   │ ───────────────►│   Node-RED      │
│   (Sensors)     │                │   (Gateway)     │                 │   (Alarms)      │
│                 │                │                 │                 │                 │
│ • AHT20 (Temp)  │                │ • ble_gateway   │                 │ • Thresholds    │
│ • MH-Series     │                │ • cloud_sync    │                 │ • Alerts        │
│ • Soil Moisture │                │ • MQTT Broker   │                 │                 │
│ • MQ-135 (Air)  │                │                 │                 │                 │
└─────────────────┘                └────────┬────────┘                 └─────────────────┘
                                           │
                                           │ MQTT (Async)
                                           │
                                           ▼
                                   ┌─────────────────┐
                                   │   OpenStack     │
                                   │    (Cloud)      │
                                   │                 │
                                   │ • MQTT Broker   │
                                   │ • Data Storage  │
                                   │ • Analytics     │
                                   └─────────────────┘
```

## Data Flow

1. **ESP32** reads sensors every 5 seconds
2. **ESP32** broadcasts data via BLE notification
3. **ble_gateway.py** receives BLE data, publishes to local MQTT
4. **Node-RED** subscribes to local MQTT, checks thresholds, generates alarms
5. **cloud_sync.py** subscribes to local MQTT, forwards to OpenStack MQTT broker

## Hardware Components

| Component | Model | ESP32 Pin | Notes |
|-----------|-------|-----------|-------|
| Temperature/Humidity | AHT20 | GPIO 21 (SDA), GPIO 22 (SCL) | I2C, 3.3V |
| Light Sensor | MH-Series LDR | GPIO 32 | Analogue, 3.3V |
| Soil Moisture | Capacitive | GPIO 34 | Analogue, 3.3V |
| Air Quality | Mikroe-1630 (MQ-135) | GPIO 35 | Analogue, **5V required** |

## Software Components

### 1. ESP32 Firmware (`esp32/agrisense_sensor.ino`)

Single Arduino sketch handling all sensors and BLE communication.

**Libraries Required:**
- Adafruit AHTX0
- ArduinoJson

**Configuration:**
```cpp
#define DEVICE_NAME "AgriSense-001"    // Change for each node
#define LOCATION "Greenhouse-A"         // Location identifier
```

### 2. BLE Gateway (`raspberry_pi/ble_gateway.py`)

Receives BLE notifications from ESP32 nodes and publishes to MQTT.

```bash
# Install dependencies
pip install bleak paho-mqtt

# Run
python ble_gateway.py
```

### 3. Cloud Sync (`raspberry_pi/cloud_sync.py`)

Asynchronous synchronisation between edge and OpenStack cloud via MQTT.

**Features:**
- Batches readings for efficient transmission
- Offline queue (SQLite) for network outages
- Automatic reconnection
- Bidirectional communication (can receive commands from cloud)

```bash
# Install dependencies
pip install paho-mqtt

# Test cloud connection
python cloud_sync.py --test --cloud-ip YOUR_OPENSTACK_IP

# Run with default settings
python cloud_sync.py

# Run with custom settings
python cloud_sync.py --cloud-ip 51.107.8.227 --edge-id greenhouse-01
```

**Configuration:**
```python
# Edit cloud_sync.py or use command line arguments
CLOUD_BROKER = "51.107.8.227"    # Your OpenStack server IP
CLOUD_PORT = 1883                 # MQTT port
EDGE_ID = "edge-rpi-001"          # Unique edge identifier
```

### 4. Node-RED Alarm Flow (`nodered/alarm_flow.json`)

Threshold-based monitoring with configurable limits.

**Default Thresholds:**
| Parameter | Min | Max | Unit |
|-----------|-----|-----|------|
| Temperature | 15 | 35 | °C |
| Humidity | 30 | 85 | % |
| Light | 10 | 90 | % |
| Soil Moisture | 20 | 80 | % |
| Air Quality | 0 | 70 | Index |

## Installation

### Raspberry Pi Setup

```bash
# 1. Install system packages
sudo apt update
sudo apt install -y bluetooth bluez mosquitto mosquitto-clients nodejs npm

# 2. Install Node-RED
sudo npm install -g node-red

# 3. Install Python dependencies
pip install bleak paho-mqtt

# 4. Enable and start Mosquitto
sudo systemctl enable mosquitto
sudo systemctl start mosquitto

# 5. Copy project files
mkdir -p ~/agrisense
# Copy raspberry_pi/*.py to ~/agrisense/
# Copy nodered/*.json to ~/.node-red/

# 6. Import Node-RED flow
# Open Node-RED (http://localhost:1880)
# Import alarm_flow.json
```

### ESP32 Setup

1. Open Arduino IDE
2. Install libraries:
   - Adafruit AHTX0 (Library Manager)
   - ArduinoJson (Library Manager)
3. Open `esp32/agrisense_sensor.ino`
4. Configure device name and location
5. Upload to ESP32

### OpenStack Cloud Setup

1. Ensure MQTT broker (Mosquitto) is installed on your OpenStack instance
2. Open firewall port 1883:
   ```bash
   # On OpenStack instance
   sudo ufw allow 1883
   ```
3. Configure Mosquitto for remote connections:
   ```bash
   # /etc/mosquitto/mosquitto.conf
   listener 1883
   allow_anonymous true
   ```

## Running the System

### Start Order

1. **Mosquitto** (auto-starts on boot)
2. **Node-RED**: `node-red`
3. **BLE Gateway**: `python ble_gateway.py`
4. **Cloud Sync**: `python cloud_sync.py`
5. **ESP32**: Power on

### Running as Services

Create systemd services for automatic startup:

```bash
# /etc/systemd/system/agrisense-ble.service
[Unit]
Description=AgriSense BLE Gateway
After=bluetooth.target mosquitto.service

[Service]
ExecStart=/usr/bin/python3 /home/pi/agrisense/ble_gateway.py
WorkingDirectory=/home/pi/agrisense
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

```bash
# /etc/systemd/system/agrisense-cloud.service
[Unit]
Description=AgriSense Cloud Sync
After=network.target mosquitto.service

[Service]
ExecStart=/usr/bin/python3 /home/pi/agrisense/cloud_sync.py
WorkingDirectory=/home/pi/agrisense
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

Enable services:
```bash
sudo systemctl enable agrisense-ble agrisense-cloud
sudo systemctl start agrisense-ble agrisense-cloud
```

## MQTT Topics

| Topic | Direction | Description |
|-------|-----------|-------------|
| `agrisense/sensors/data` | ESP32 → Cloud | Sensor readings |
| `agrisense/alarms` | Node-RED → Cloud | Threshold alerts |
| `agrisense/commands/{edge_id}` | Cloud → Edge | Remote commands |

## JSON Payload Format

### Sensor Reading
```json
{
    "node_id": "AgriSense-001",
    "location": "Greenhouse-A",
    "temperature": 25.5,
    "humidity": 65.0,
    "light": 75,
    "light_raw": 1200,
    "soil": 45,
    "soil_raw": 2500,
    "air_quality": 22,
    "air_raw": 350,
    "edge_id": "edge-rpi-001",
    "edge_name": "AgriSense Gateway",
    "received_at": "2024-01-15T10:30:00"
}
```

### Alarm
```json
{
    "node_id": "AgriSense-001",
    "violations": ["temperature > 35"],
    "timestamp": "2024-01-15T10:30:00"
}
```

## Troubleshooting

### BLE Connection Issues
```bash
# Check Bluetooth status
sudo systemctl status bluetooth
sudo hciconfig

# Scan for devices
sudo hcitool lescan
```

### MQTT Issues
```bash
# Test local MQTT
mosquitto_sub -t "agrisense/#" -v

# Test cloud MQTT
mosquitto_pub -h YOUR_CLOUD_IP -t "test" -m "hello"
```

### Cloud Sync Issues
```bash
# Test connection
python cloud_sync.py --test --cloud-ip YOUR_IP

# Check offline queue
sqlite3 offline_queue.db "SELECT COUNT(*) FROM reading_queue WHERE status='pending'"
```

## Files

```
agrisense-minimal/
├── esp32/
│   └── agrisense_sensor.ino    # ESP32 firmware (all sensors)
├── raspberry_pi/
│   ├── ble_gateway.py          # BLE to MQTT bridge
│   └── cloud_sync.py           # MQTT to OpenStack sync
├── nodered/
│   └── alarm_flow.json         # Threshold monitoring
└── README.md
```
