# AgriSense Sensor API

A comprehensive IoT sensor data collection system that receives environmental data from distributed sensor nodes via MQTT and stores it in a PostgreSQL database. Built for precision agriculture monitoring with edge computing capabilities using Raspberry Pi sensor nodes.

## Architecture

- **MQTT Broker**: Mosquitto (running on port 1883)
- **Database**: PostgreSQL with extended schema for edge and location tracking
- **MQTT Worker**: Python service that subscribes to sensor topics and persists data
- **Data Flow**: Sensor Nodes → Edge Gateway (RPi) → MQTT → Worker → PostgreSQL

## Prerequisites

- Ubuntu/Debian-based system
- Python 3.x
- PostgreSQL
- Mosquitto MQTT Broker
- Root/sudo access

## Installation

### 1. Database Setup

Install PostgreSQL:
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
```

Create the database and user:
```bash
sudo -i -u postgres
psql
```

Run the following SQL commands:
```sql
CREATE DATABASE agrisensedb;
CREATE USER admin WITH ENCRYPTED PASSWORD 'agrisense';
GRANT ALL PRIVILEGES ON DATABASE agrisensedb TO admin;
\c agrisensedb
GRANT ALL ON SCHEMA public TO admin;

CREATE TABLE tagrisense (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc'),
    node_id varchar(50),
    location VARCHAR(100), 
    edge_id VARCHAR(50),   
    edge_name VARCHAR(50), 
    edge_location VARCHAR(100),
    metric VARCHAR(50),       
    value DOUBLE PRECISION    
);

CREATE INDEX idx_agrisense_timestamp ON tagrisense(timestamp);
CREATE INDEX idx_agrisense_metric ON tagrisense(metric);
\q
exit
```

### 2. Environment Setup

Create project directory:
```bash
cd ~
mkdir -p sensor_api
cd sensor_api
```

Install system dependencies:
```bash
sudo apt install python3-venv mosquitto mosquitto-clients -y
```

Configure Mosquitto for external access:
```bash
sudo bash -c 'echo "listener 1883" > /etc/mosquitto/conf.d/default.conf'
sudo bash -c 'echo "allow_anonymous true" >> /etc/mosquitto/conf.d/default.conf'
sudo systemctl restart mosquitto
sudo systemctl enable mosquitto
```

Set up Python virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn psycopg2-binary pydantic paho-mqtt
```

### 3. Deploy MQTT Worker

Create `mqtt_worker.py` in the `sensor_api` directory with the code provided in the source document.

**Important Configuration Variables:**
- `MQTT_HOST`: Your server's IP address (currently set to `172.22.249.96`)
- `MQTT_PORT`: MQTT broker port (default: `1883`)
- `MQTT_TOPIC_SENSORS`: Topic to subscribe to (default: `agrisense/sensors/data`)
- `MQTT_TOPIC_ALARM`: Topic to subscribe to receive alert (default: `agrisense/alarms`)
- `DB_CONFIG`: Database connection parameters

### 4. Create Systemd Service

Create the service file:
```bash
sudo nano /etc/systemd/system/sensor_mqtt.service
```

Add the following configuration:
```ini
[Unit]
Description=MQTT Worker for AgriSense
After=network.target mosquitto.service

[Service]
User=student
Group=student
WorkingDirectory=/home/student/sensor_api
Environment="PATH=/home/student/sensor_api/venv/bin"
ExecStart=/home/student/sensor_api/python mqtt_worker.py
Restart=always

[Install]
WantedBy=multi-user.target
```

**Note**: Adjust `User`, `Group`, and `WorkingDirectory` paths according to your system setup.

### 5. Start the Service

Enable and start the MQTT worker:
```bash
sudo systemctl daemon-reload
sudo systemctl start sensor_mqtt
sudo systemctl enable sensor_mqtt
```

## Usage

### Check Service Status
```bash
sudo systemctl status sensor_mqtt
```

### View Logs
```bash
sudo journalctl -u sensor_mqtt -f
```

### Test MQTT Broker
Publish a test message:
```bash
mosquitto_pub -h localhost -t agrisense/sensors/data -m '{
  "node_id": "sensor_001",
  "location": "Greenhouse_A",
  "edge_id": "edge_rpi_01",
  "edge_name": "RPi_North_Sector",
  "edge_location": "Building_A_Room_12",
  "received_at": "2025-01-06T10:30:00",
  "temperature": 22.5,
  "humidity": 65.3,
  "soil": 45.2,
  "light": 850,
  "air_quality": 100
}'
```

### Query Database
Connect to the database:
```bash
psql -h localhost -d agrisensedb -U admin -W
```

View recent sensor readings:
```sql
SELECT * FROM tagrisense ORDER BY id DESC LIMIT 5;
```

View data by sensor node:
```sql
SELECT node_id, location, edge_name, metric, value, timestamp 
FROM tagrisense 
WHERE node_id = 'sensor_001' 
ORDER BY timestamp DESC 
LIMIT 10;
```

View data by edge gateway:
```sql
SELECT edge_id, edge_name, node_id, metric, value, timestamp 
FROM tagrisense 
WHERE edge_id = 'edge_rpi_01' 
ORDER BY timestamp DESC;
```

View specific metrics across all sensors:
```sql
SELECT node_id, location, metric, value, timestamp 
FROM tagrisense 
WHERE metric = 'temperature' 
ORDER BY timestamp DESC 
LIMIT 10;
```

Aggregate data by location:
```sql
SELECT location, metric, 
       AVG(value) as avg_value, 
       MIN(value) as min_value, 
       MAX(value) as max_value
FROM tagrisense 
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY location, metric;
```

## Data Format

### Expected MQTT Payload
The system expects JSON payloads with the following structure:
```json
{
  "node_id": "sensor_001",
  "location": "Greenhouse_A_Section_1",
  "edge_id": "edge_rpi_01",
  "edge_name": "RPi_Gateway_North",
  "edge_location": "Control_Room_A",
  "received_at": "2025-01-06T10:30:00",
  "temperature": 22.5,
  "humidity": 65.3,
  "soil": 45.2,
  "light": 850,
  "air_quality": 100
}
```

### Database Schema
Each metric from the payload is stored as a separate row in the `tagrisense` table:

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL | Auto-incrementing primary key |
| `timestamp` | TIMESTAMP | Automatically set to current UTC time or from `received_at` |
| `node_id` | VARCHAR(50) | Unique identifier of the sensor node |
| `location` | VARCHAR(100) | Physical location of the sensor node |
| `edge_id` | VARCHAR(50) | Unique identifier of the edge gateway |
| `edge_name` | VARCHAR(50) | Human-readable name of the edge gateway |
| `edge_location` | VARCHAR(100) | Physical location of the edge gateway |
| `metric` | VARCHAR(50) | Name of the measurement (e.g., "temperature", "humidity") |
| `value` | DOUBLE PRECISION | Numerical value of the measurement |

**Note**: The system automatically excludes metadata fields (`node_id`, `location`, `received_at`, `edge_id`, `edge_name`, `edge_location`) from being stored as metrics.

## Troubleshooting

### Service Won't Start
Check logs for errors:
```bash
sudo journalctl -u sensor_mqtt -n 50
```

Verify the Python path in the service file:
```bash
which python
# Update ExecStart path if needed
```

### Cannot Connect to MQTT Broker
Verify Mosquitto is running:
```bash
sudo systemctl status mosquitto
```

Test local connection:
```bash
mosquitto_sub -h localhost -t agrisense/sensors/data -v
```

Check Mosquitto logs:
```bash
sudo tail -f /var/log/mosquitto/mosquitto.log
```

### Database Connection Issues
Verify PostgreSQL is running:
```bash
sudo systemctl status postgresql
```

Test database connection:
```bash
psql -h localhost -d agrisensedb -U admin -W
```

Check database logs:
```bash
sudo tail -f /var/log/postgresql/postgresql-*.log
```

### Permission Issues
Ensure the service user has access to the project directory:
```bash
sudo chown -R student:student /home/student/sensor_api
```

Verify Python virtual environment:
```bash
source /home/student/sensor_api/venv/bin/activate
which python
pip list
```

### Data Not Being Saved
Check MQTT message format:
```bash
# Subscribe to see incoming messages
mosquitto_sub -h localhost -t agrisense/sensors/data -v
```

Verify the payload matches expected JSON structure:
- Must include `node_id`
- Metric values should be numeric (not strings)
- Avoid null or "N/A" values

Check for Python errors in service logs:
```bash
sudo journalctl -u sensor_mqtt -f
```

## Project Structure

```
sensor_api/
├── mqtt_worker.py          # Main MQTT worker script
├── venv/                   # Python virtual environment
├── README.md               # This file
└── logs/                   # Application logs (optional)
```

## Performance Considerations

- **Database Indexing**: Indexes on `timestamp` and `metric` columns improve query performance
- **Connection Pooling**: Consider implementing connection pooling for high-throughput scenarios
- **Batch Inserts**: For very high data rates, consider batching database inserts
- **Data Retention**: Implement policies to archive or delete old data to maintain performance
- **Monitoring**: Use tools like Grafana + Prometheus for system monitoring

## Support

For issues or questions, please contact the development team.

## Contributors

- Jeremy Dion Purnama
- Ngoc Duc Anh Nguyen
- Animashaun Tolulope Ibrahim
- William Hart
