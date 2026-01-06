# AgriSense Database Queries

This guide shows how to query the SQLite database on your Raspberry Pi.

## Database Location

```bash
~/agrisense/agrisense_data.db
```

## Access the Database

```bash
cd ~/agrisense
sqlite3 agrisense_data.db
```

---

## Common Queries

### 1. View Database Schema

```sql
.schema sensor_readings
```

### 2. Count Total Readings

```sql
SELECT COUNT(*) as total_readings FROM sensor_readings;
```

### 3. View Latest 10 Readings

```sql
SELECT
    timestamp,
    node_id,
    temperature,
    humidity,
    soil,
    light,
    air_quality,
    air_ppm
FROM sensor_readings
ORDER BY id DESC
LIMIT 10;
```

### 4. View Latest Reading with All Fields

```sql
SELECT * FROM sensor_readings ORDER BY id DESC LIMIT 1;
```

### 5. View Readings from Specific Node

```sql
SELECT
    timestamp,
    temperature,
    humidity,
    soil,
    light,
    air_quality,
    air_ppm
FROM sensor_readings
WHERE node_id = 'AgriSense-003'
ORDER BY id DESC
LIMIT 20;
```

### 6. View Readings from Last Hour

```sql
SELECT
    timestamp,
    node_id,
    temperature,
    humidity,
    soil,
    light,
    air_quality,
    air_ppm
FROM sensor_readings
WHERE datetime(timestamp) >= datetime('now', '-1 hour')
ORDER BY timestamp DESC;
```

### 7. View Readings from Last 24 Hours

```sql
SELECT
    timestamp,
    node_id,
    temperature,
    humidity,
    soil,
    light,
    air_quality,
    air_ppm
FROM sensor_readings
WHERE datetime(timestamp) >= datetime('now', '-24 hours')
ORDER BY timestamp DESC;
```

### 8. Average Values from Last Hour

```sql
SELECT
    node_id,
    ROUND(AVG(temperature), 1) as avg_temp,
    ROUND(AVG(humidity), 1) as avg_humidity,
    ROUND(AVG(soil), 1) as avg_soil,
    ROUND(AVG(light), 1) as avg_light,
    ROUND(AVG(air_quality), 1) as avg_air_quality,
    ROUND(AVG(air_ppm), 1) as avg_co2_ppm,
    COUNT(*) as reading_count
FROM sensor_readings
WHERE datetime(timestamp) >= datetime('now', '-1 hour')
GROUP BY node_id;
```

### 9. Min/Max Temperature from Last 24 Hours

```sql
SELECT
    node_id,
    MIN(temperature) as min_temp,
    MAX(temperature) as max_temp,
    ROUND(AVG(temperature), 1) as avg_temp
FROM sensor_readings
WHERE datetime(timestamp) >= datetime('now', '-24 hours')
GROUP BY node_id;
```

### 10. High CO2 Readings (> 1000 PPM)

```sql
SELECT
    timestamp,
    node_id,
    air_quality,
    air_ppm,
    temperature,
    humidity
FROM sensor_readings
WHERE air_ppm > 1000
ORDER BY timestamp DESC
LIMIT 20;
```

### 11. Readings by Hour (Last 24 Hours)

```sql
SELECT
    strftime('%Y-%m-%d %H:00', timestamp) as hour,
    COUNT(*) as readings,
    ROUND(AVG(temperature), 1) as avg_temp,
    ROUND(AVG(humidity), 1) as avg_humidity,
    ROUND(AVG(air_ppm), 1) as avg_co2
FROM sensor_readings
WHERE datetime(timestamp) >= datetime('now', '-24 hours')
GROUP BY hour
ORDER BY hour DESC;
```

### 12. Delete Old Data (Older than 7 Days)

```sql
DELETE FROM sensor_readings
WHERE datetime(timestamp) < datetime('now', '-7 days');
```

### 13. Database Size and Row Count

```bash
# In bash (not in sqlite)
ls -lh ~/agrisense/agrisense_data.db
sqlite3 ~/agrisense/agrisense_data.db "SELECT COUNT(*) FROM sensor_readings;"
```

---

## Export Data to CSV

### Export Last 100 Readings

```bash
sqlite3 -header -csv ~/agrisense/agrisense_data.db \
  "SELECT timestamp, node_id, temperature, humidity, soil, light, air_quality, air_ppm
   FROM sensor_readings
   ORDER BY id DESC
   LIMIT 100;" > readings.csv
```

### Export Today's Data

```bash
sqlite3 -header -csv ~/agrisense/agrisense_data.db \
  "SELECT * FROM sensor_readings
   WHERE DATE(timestamp) = DATE('now');" > today_readings.csv
```

### Export All Data

```bash
sqlite3 -header -csv ~/agrisense/agrisense_data.db \
  "SELECT * FROM sensor_readings;" > all_readings.csv
```

---

## Formatted Table Output

Enable better formatting in SQLite:

```sql
.mode column
.headers on
.width 20 15 8 8 6 6 10 8
```

Then run your queries for nicely formatted output.

---

## Python Script to Query Database

Create `query_db.py`:

```python
#!/usr/bin/env python3
import sqlite3
from datetime import datetime, timedelta

DB_FILE = "/home/pi/agrisense/agrisense_data.db"

def query_latest(limit=10):
    """Query latest readings"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT
            timestamp, node_id, temperature, humidity,
            soil, light, air_quality, air_ppm
        FROM sensor_readings
        ORDER BY id DESC
        LIMIT ?
    ''', (limit,))

    print(f"\n{'Timestamp':<20} {'Node':<15} {'Temp':<6} {'Hum':<6} {'Soil':<6} {'Light':<6} {'Air':<6} {'CO2':<8}")
    print("-" * 90)

    for row in cursor.fetchall():
        timestamp, node_id, temp, hum, soil, light, air, co2 = row
        print(f"{timestamp:<20} {node_id:<15} {temp:<6.1f} {hum:<6.1f} {soil:<6} {light:<6} {air:<6} {co2:<8.1f}")

    conn.close()

def query_averages(hours=1):
    """Query averages for last N hours"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT
            node_id,
            COUNT(*) as count,
            ROUND(AVG(temperature), 1) as avg_temp,
            ROUND(AVG(humidity), 1) as avg_hum,
            ROUND(AVG(soil), 1) as avg_soil,
            ROUND(AVG(light), 1) as avg_light,
            ROUND(AVG(air_ppm), 1) as avg_co2
        FROM sensor_readings
        WHERE datetime(timestamp) >= datetime('now', ?)
        GROUP BY node_id
    ''', (f'-{hours} hours',))

    print(f"\nAverages (Last {hours} hour(s)):")
    print(f"{'Node':<15} {'Count':<8} {'Temp':<8} {'Hum':<8} {'Soil':<8} {'Light':<8} {'CO2':<8}")
    print("-" * 75)

    for row in cursor.fetchall():
        node, count, temp, hum, soil, light, co2 = row
        print(f"{node:<15} {count:<8} {temp:<8} {hum:<8} {soil:<8} {light:<8} {co2:<8}")

    conn.close()

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "avg":
        hours = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        query_averages(hours)
    else:
        limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
        query_latest(limit)
```

Make it executable:

```bash
chmod +x query_db.py
```

Usage:

```bash
# Latest 10 readings
./query_db.py

# Latest 50 readings
./query_db.py 50

# Averages for last hour
./query_db.py avg 1

# Averages for last 24 hours
./query_db.py avg 24
```

---

## One-Line Commands

### Quick Stats

```bash
# Total readings
sqlite3 ~/agrisense/agrisense_data.db "SELECT COUNT(*) FROM sensor_readings;"

# Latest reading
sqlite3 ~/agrisense/agrisense_data.db "SELECT timestamp, node_id, temperature, humidity, air_ppm FROM sensor_readings ORDER BY id DESC LIMIT 1;"

# Average CO2 today
sqlite3 ~/agrisense/agrisense_data.db "SELECT ROUND(AVG(air_ppm), 1) FROM sensor_readings WHERE DATE(timestamp) = DATE('now');"
```

---

## Exit SQLite

```sql
.quit
```

Or press `Ctrl+D`

---

## Troubleshooting

### Database Locked

If you get "database is locked" error:

```bash
# Stop the BLE gateway service temporarily
sudo systemctl stop agrisense-ble

# Query the database
sqlite3 ~/agrisense/agrisense_data.db "YOUR QUERY HERE"

# Restart the service
sudo systemctl start agrisense-ble
```

### Vacuum Database (Reduce File Size)

```bash
sqlite3 ~/agrisense/agrisense_data.db "VACUUM;"
```
