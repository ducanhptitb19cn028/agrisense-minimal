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
│ • MQ-135 (Air)  │                │ • SQLite DB     │                 │                 │
└─────────────────┘                └────────┬────────┘                 └─────────────────┘
                                           │
                                           │ MQTT (Real-time)
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

## Hardware Components

| Component | Model | ESP32 Pin | Notes |
|-----------|-------|-----------|-------|
| Temperature/Humidity | AHT20 | GPIO 21 (SDA), GPIO 22 (SCL) | I2C, 3.3V |
| Light Sensor | MH-Series LDR | GPIO 32 | Analogue, 3.3V |
| Soil Moisture | Capacitive | GPIO 34 | Analogue, 3.3V |
| Air Quality | Mikroe-1630 (MQ-135) | GPIO 35 | Analogue, **5V required** |

---

## Quick Start

### 1. Raspberry Pi Setup

```bash
# Install system packages
sudo apt update
sudo apt install -y bluetooth bluez mosquitto mosquitto-clients python3-pip sqlite3 nodejs npm

# Install Python dependencies
pip3 install bleak paho-mqtt

# Enable services
sudo systemctl enable bluetooth mosquitto
sudo systemctl start bluetooth mosquitto

# Create project directory
mkdir -p ~/agrisense
cd ~/agrisense

# Copy files: ble_gateway.py and cloud_sync.py to ~/agrisense/

# Configure cloud IP
nano cloud_sync.py  # Change CLOUD_BROKER to your OpenStack IP
```

### 2. ESP32 Setup

1. Open Arduino IDE
2. Install libraries: `Adafruit AHTX0`, `ArduinoJson`
3. Open `esp32/agrisense_sensor/agrisense_sensor.ino`
4. Configure device name and location
5. Upload to ESP32

### 3. Node-RED Dashboard Setup

```bash
# Install Node-RED
sudo npm install -g --unsafe-perm node-red

# Install dashboard nodes
cd ~/.node-red
npm install node-red-dashboard

# Start Node-RED
node-red
```

Access Node-RED at `http://localhost:1880`

**Import the dashboard flow:**
1. Open Node-RED editor (`http://localhost:1880`)
2. Click menu (☰) → Import
3. Select `nodered/dashboard_flow.json`
4. Click Deploy

**Access the dashboard:** `http://localhost:1880/ui`

**📖 See [nodered/DASHBOARD_GUIDE.md](nodered/DASHBOARD_GUIDE.md) for detailed dashboard features and layout**

### 4. Run the System

```bash
# Terminal 1 - BLE Gateway
cd ~/agrisense
python3 ble_gateway.py

# Terminal 2 - Cloud Sync
cd ~/agrisense
python3 cloud_sync.py

# Terminal 3 - Node-RED (if not running as service)
node-red
```

**Databases are created automatically** - No manual setup needed!
- `agrisense_data.db` - Local sensor data
- `offline_queue.db` - Cloud sync queue

---

## Running as Services (Auto-Start on Boot)

### Create BLE Gateway Service

```bash
sudo nano /etc/systemd/system/agrisense-ble.service
```

Paste:
```ini
[Unit]
Description=AgriSense BLE Gateway
After=bluetooth.target mosquitto.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/agrisense
ExecStart=/usr/bin/python3 /home/pi/agrisense/ble_gateway.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Create Cloud Sync Service

```bash
sudo nano /etc/systemd/system/agrisense-cloud.service
```

Paste:
```ini
[Unit]
Description=AgriSense Cloud Sync
After=network-online.target mosquitto.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/agrisense
ExecStart=/usr/bin/python3 /home/pi/agrisense/cloud_sync.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Create Node-RED Service

```bash
sudo nano /etc/systemd/system/nodered.service
```

Paste:
```ini
[Unit]
Description=Node-RED
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi
ExecStart=/usr/bin/node-red
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Enable and Start Services

```bash
sudo systemctl daemon-reload
sudo systemctl enable agrisense-ble agrisense-cloud nodered
sudo systemctl start agrisense-ble agrisense-cloud nodered

# Check status
sudo systemctl status agrisense-ble
sudo systemctl status agrisense-cloud
sudo systemctl status nodered
```

---

## Dashboard Features

The Node-RED dashboard provides real-time visualization:

### Current Readings
- **Gauges** for all sensors (Temperature, Humidity, Soil, Light, Air Quality)
- **Color-coded** indicators (green = normal, yellow = warning, red = critical)
- **Device info** showing node ID, location, and last update time

### Historical Trends
- **Line charts** showing last hour of data for each sensor
- **Multiple devices** can be tracked on same chart
- **Auto-updating** in real-time as new data arrives

### Alarm System
- **Pop-up notifications** when thresholds are exceeded
- **Alarm panel** showing active violations with details
- **Status indicator** showing "All OK" or listing violations
- **Thresholds:**
  - Temperature: 15-35°C
  - Humidity: 30-85%
  - Light: 10-90%
  - Soil Moisture: 20-80%
  - Air Quality: 0-70 index

**Access dashboard:** `http://YOUR_RPI_IP:1880/ui`

---

## Monitoring & Management

### View Logs

```bash
# Live logs
sudo journalctl -u agrisense-ble -f
sudo journalctl -u agrisense-cloud -f

# Both together
sudo journalctl -u agrisense-ble -u agrisense-cloud -f
```

### Monitor MQTT

```bash
# All topics
mosquitto_sub -v -t "agrisense/#"

# Sensor data only
mosquitto_sub -v -t "agrisense/sensors/data"
```

### Check Database

```bash
# Count sensor readings
sqlite3 ~/agrisense/agrisense_data.db "SELECT COUNT(*) FROM sensor_readings;"

# View last 5 readings
sqlite3 ~/agrisense/agrisense_data.db "SELECT * FROM sensor_readings ORDER BY id DESC LIMIT 5;"

# Check cloud sync queue
sqlite3 ~/agrisense/offline_queue.db "SELECT COUNT(*) FROM reading_queue WHERE status='pending';"
```

### Service Commands

```bash
# Start
sudo systemctl start agrisense-ble agrisense-cloud nodered

# Stop
sudo systemctl stop agrisense-ble agrisense-cloud nodered

# Restart
sudo systemctl restart agrisense-ble agrisense-cloud nodered

# Status
sudo systemctl status agrisense-ble agrisense-cloud nodered

# View Node-RED logs
sudo journalctl -u nodered -f
```

---

## Configuration

### Cloud Sync (`cloud_sync.py`)

Edit line ~49:
```python
CLOUD_BROKER = "172.22.249.96"  # Your OpenStack IP
CLOUD_PORT = 1883
REALTIME_MODE = True             # Send data immediately
BATCH_SIZE = 1                   # Readings per batch
BATCH_TIMEOUT = 2                # Batch timeout (seconds)
```

Command-line options:
```bash
# Test cloud connection
python3 cloud_sync.py --test --cloud-ip YOUR_IP

# Custom settings
python3 cloud_sync.py --cloud-ip 172.22.249.96 --edge-id greenhouse-01

# Use batch mode
python3 cloud_sync.py --no-realtime --batch-size 10 --batch-timeout 30
```

### ESP32 Firmware

Edit in `agrisense_sensor.ino`:
```cpp
#define DEVICE_NAME "AgriSense-001"    // Change for each node
#define LOCATION "Greenhouse-A"         // Location identifier
```

---

## Data Format

### Sensor Reading (MQTT: `agrisense/sensors/data`)

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

All sensor data is sent to cloud in **real-time** with no filtering.

---

## Troubleshooting

### ESP32 Not Found

```bash
# Check Bluetooth
sudo systemctl status bluetooth
sudo hcitool lescan

# Restart Bluetooth
sudo systemctl restart bluetooth
```

### Cloud Connection Failed

```bash
# Test connection
python3 cloud_sync.py --test --cloud-ip YOUR_IP

# Check network
ping YOUR_OPENSTACK_IP

# Check firewall on OpenStack
sudo ufw allow 1883
```

### Check Logs for Errors

```bash
# BLE Gateway logs
sudo journalctl -u agrisense-ble -n 50

# Cloud Sync logs
sudo journalctl -u agrisense-cloud -n 50
```

### Database Issues

```bash
# Check database exists
ls -lh ~/agrisense/*.db

# Verify integrity
sqlite3 ~/agrisense/agrisense_data.db "PRAGMA integrity_check;"

# Rebuild (deletes data)
rm ~/agrisense/*.db
sudo systemctl restart agrisense-ble agrisense-cloud
```

---

## OpenStack Cloud Setup

On your OpenStack instance:

```bash
# Install MQTT broker
sudo apt install -y mosquitto mosquitto-clients

# Configure for remote connections
sudo nano /etc/mosquitto/mosquitto.conf
```

Add:
```
listener 1883
allow_anonymous true
```

```bash
# Open firewall
sudo ufw allow 1883

# Restart Mosquitto
sudo systemctl restart mosquitto
```

---

## Project Files

```
agrisense-minimal/
├── esp32/
│   └── agrisense_sensor/
│       └── agrisense_sensor.ino    # ESP32 firmware
├── raspberry_pi/
│   ├── ble_gateway.py              # BLE to MQTT bridge
│   └── cloud_sync.py               # Cloud sync (real-time)
├── nodered/
│   ├── alarm_flow.json             # Basic alarm monitoring
│   ├── dashboard_flow.json         # Full dashboard with visualization
│   └── DASHBOARD_GUIDE.md          # Dashboard user guide
└── README.md
```

---

## Data Flow

1. **ESP32** reads sensors every 5 seconds
2. **ESP32** broadcasts via BLE
3. **ble_gateway.py** receives BLE → saves to SQLite → publishes to MQTT
4. **cloud_sync.py** subscribes to MQTT → sends to OpenStack (real-time)
5. If cloud offline → queues in SQLite → auto-retries every 5 seconds

**All sensor data is sent to cloud with zero data loss.**

---

## Quick Reference

```bash
# Check if running
sudo systemctl status agrisense-*

# View live logs
sudo journalctl -u agrisense-ble -u agrisense-cloud -u nodered -f

# Monitor MQTT
mosquitto_sub -v -t "agrisense/#"

# Check data count
sqlite3 ~/agrisense/agrisense_data.db "SELECT COUNT(*) FROM sensor_readings;"

# Test cloud
python3 cloud_sync.py --test --cloud-ip YOUR_IP

# Access dashboards
# Node-RED editor: http://localhost:1880
# Live dashboard:  http://localhost:1880/ui
```

---

**System ready! View real-time sensor data and alarms at `http://YOUR_RPI_IP:1880/ui`**
