/*
 * AgriSense ESP32 Multi-Sensor Node - BLE Version
 * 
 * Sensors:
 * - AHT20: Temperature & Humidity (I2C)
 * - MH-Series: Light intensity (Analog LDR)
 * - Capacitive: Soil moisture (Analog)
 * - Mikroe-1630 (MQ-135): Air quality (Analog)
 * 
 * Communication: Bluetooth Low Energy (BLE)
 * 
 * Libraries Required:
 * - Adafruit AHTX0
 * - ArduinoJson
 */

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <Wire.h>
#include <Adafruit_AHTX0.h>
#include <ArduinoJson.h>

// ============== CONFIGURATION ==============

// Device Identity - CHANGE FOR EACH NODE
#define DEVICE_NAME "AgriSense-002"
#define LOCATION "Greenhouse-A"

// Pin Definitions
#define I2C_SDA 21
#define I2C_SCL 22
#define LIGHT_PIN 36        // MH-Series LDR
#define SOIL_PIN 34         // Capacitive soil moisture
#define AIR_PIN 35          // Mikroe-1630 / MQ-135
#define LED_PIN 2

// Calibration Values
// Light sensor (MH-Series): Lower ADC = brighter
#define LIGHT_BRIGHT 500    // ADC value in bright light
#define LIGHT_DARK 4000     // ADC value in darkness

// Soil moisture: Lower ADC = wetter
#define SOIL_DRY 3500
#define SOIL_WET 1500

// Air quality: Higher ADC = more polluted
#define AIR_CLEAN 100
#define AIR_POLLUTED 1000

// Reading interval
#define READING_INTERVAL 5000  // 5 seconds

// ============== BLE UUIDs ==============

#define SERVICE_UUID        "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define DATA_CHAR_UUID      "beb5483e-36e1-4688-b7f5-ea07361b26a8"

// ============== GLOBAL OBJECTS ==============

Adafruit_AHTX0 aht;
bool ahtFound = false;

BLEServer* pServer = NULL;
BLECharacteristic* pDataChar = NULL;

bool deviceConnected = false;
unsigned long lastReadingTime = 0;

// ============== BLE CALLBACKS ==============

class ServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
        deviceConnected = true;
        Serial.println("✓ Client connected");
        digitalWrite(LED_PIN, HIGH);
    }

    void onDisconnect(BLEServer* pServer) {
        deviceConnected = false;
        Serial.println("✗ Client disconnected");
        digitalWrite(LED_PIN, LOW);
        
        // Restart advertising
        delay(500);
        pServer->startAdvertising();
    }
};

// ============== SETUP ==============

void setup() {
    Serial.begin(115200);
    delay(100);
    
    Serial.println("\n========================================");
    Serial.println("  AgriSense Multi-Sensor Node (BLE)");
    Serial.println("========================================");
    Serial.printf("  Device:   %s\n", DEVICE_NAME);
    Serial.printf("  Location: %s\n", LOCATION);
    Serial.println("----------------------------------------\n");
    
    // Initialise pins
    pinMode(LED_PIN, OUTPUT);
    pinMode(LIGHT_PIN, INPUT);
    pinMode(SOIL_PIN, INPUT);
    pinMode(AIR_PIN, INPUT);
    
    // Initialise I2C and AHT20
    Wire.begin(I2C_SDA, I2C_SCL);
    
    Serial.print("AHT20 sensor: ");
    if (aht.begin()) {
        ahtFound = true;
        Serial.println("✓ Found");
    } else {
        Serial.println("✗ Not found");
    }
    
    // Initialise BLE
    Serial.print("BLE: ");
    BLEDevice::init(DEVICE_NAME);
    
    pServer = BLEDevice::createServer();
    pServer->setCallbacks(new ServerCallbacks());
    
    BLEService* pService = pServer->createService(SERVICE_UUID);
    
    pDataChar = pService->createCharacteristic(
        DATA_CHAR_UUID,
        BLECharacteristic::PROPERTY_READ |
        BLECharacteristic::PROPERTY_NOTIFY
    );
    pDataChar->addDescriptor(new BLE2902());
    
    pService->start();
    
    BLEAdvertising* pAdvertising = BLEDevice::getAdvertising();
    pAdvertising->addServiceUUID(SERVICE_UUID);
    pAdvertising->setScanResponse(true);
    BLEDevice::startAdvertising();
    
    Serial.println("✓ Advertising");
    Serial.println("\nWaiting for connection...\n");
}

// ============== MAIN LOOP ==============

void loop() {
    unsigned long now = millis();
    
    if (now - lastReadingTime >= READING_INTERVAL) {
        lastReadingTime = now;
        readAndBroadcast();
    }
    
    // Blink LED when not connected
    if (!deviceConnected) {
        digitalWrite(LED_PIN, (millis() / 1000) % 2);
    }
    
    delay(100);
}

// ============== SENSOR READING ==============

void readAndBroadcast() {
    // Create JSON document
    StaticJsonDocument<512> doc;
    
    doc["node_id"] = DEVICE_NAME;
    doc["location"] = LOCATION;
    
    // Read AHT20 (Temperature & Humidity)
    if (ahtFound) {
        sensors_event_t humidity, temp;
        aht.getEvent(&humidity, &temp);
        
        if (!isnan(temp.temperature)) {
            doc["temperature"] = round(temp.temperature * 10) / 10.0;
        }
        if (!isnan(humidity.relative_humidity)) {
            doc["humidity"] = round(humidity.relative_humidity * 10) / 10.0;
        }
    }
    
    // Read Light Sensor (MH-Series LDR)
    int lightRaw = analogRead(LIGHT_PIN);
    // Invert: MH-Series outputs lower values in bright light
    float lightPercent = map(constrain(lightRaw, LIGHT_BRIGHT, LIGHT_DARK), 
                             LIGHT_DARK, LIGHT_BRIGHT, 0, 100);
    doc["light"] = (int)lightPercent;
    doc["light_raw"] = lightRaw;
    
    // Read Soil Moisture
    int soilRaw = analogRead(SOIL_PIN);
    float soilPercent = map(constrain(soilRaw, SOIL_WET, SOIL_DRY), 
                            SOIL_DRY, SOIL_WET, 0, 100);
    doc["soil"] = (int)soilPercent;
    doc["soil_raw"] = soilRaw;
    
    // Read Air Quality (MQ-135)
    int airRaw = analogRead(AIR_PIN);
    float airIndex = map(constrain(airRaw, AIR_CLEAN, AIR_POLLUTED), 
                         AIR_CLEAN, AIR_POLLUTED, 0, 100);
    doc["air_quality"] = (int)airIndex;
    doc["air_raw"] = airRaw;
    
    // Serialise to JSON
    String payload;
    serializeJson(doc, payload);
    
    // Print to Serial
    Serial.println("Sensor Reading:");
    Serial.printf("   Temp: %.1f°C, Humidity: %.1f%%\n", 
                  doc["temperature"].as<float>(), 
                  doc["humidity"].as<float>());
    Serial.printf("   Light: %d%%, Soil: %d%%, Air: %d\n",
                  doc["light"].as<int>(),
                  doc["soil"].as<int>(),
                  doc["air_quality"].as<int>());
    
    // Broadcast via BLE
    if (deviceConnected) {
        pDataChar->setValue(payload.c_str());
        pDataChar->notify();
        Serial.println("Sent via BLE");
    } else {
        Serial.println("No client connected");
    }
    
    Serial.println();
}
