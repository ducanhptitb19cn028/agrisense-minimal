/*
 * AgriSense ESP32 Multi-Sensor Node - BLE Version
 *
 * Sensors:
 * - AHT20: Temperature & Humidity (I2C)
 * - MH-Series: Light intensity (Analog LDR)
 * - Capacitive: Soil moisture (Analog)
 * - Mikroe-1630 (MQ-135): Air quality (CO2 PPM via MQUnifiedsensor)
 *
 * Communication: Bluetooth Low Energy (BLE)
 *
 * Libraries Required:
 * - Adafruit AHTX0
 * - ArduinoJson
 * - MQUnifiedsensor
 */

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <Wire.h>
#include <Adafruit_AHTX0.h>
#include <ArduinoJson.h>
#include <MQUnifiedsensor.h>

// ============== CONFIGURATION ==============

// Device Identity - CHANGE FOR EACH NODE
#define DEVICE_NAME "AgriSense-003"
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

// MQ-135 Configuration
#define MQ135_BOARD "ESP32"
#define MQ135_VOLTAGE_RESOLUTION 5
#define MQ135_ADC_BIT_RESOLUTION 12  // ESP32 ADC is 12-bit (0-4095)
#define MQ135_RATIO_CLEAN_AIR 3.6    // RS/R0 ratio in clean air
#define MQ135_RL_VALUE 10            // Load resistance in kOhms

// Reading interval
#define READING_INTERVAL 5000  // 5 seconds

// ============== BLE UUIDs ==============

#define SERVICE_UUID        "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define DATA_CHAR_UUID      "beb5483e-36e1-4688-b7f5-ea07361b26a8"

// ============== GLOBAL OBJECTS ==============

Adafruit_AHTX0 aht;
bool ahtFound = false;

// MQ-135 Sensor Object
MQUnifiedsensor MQ135(MQ135_BOARD, MQ135_VOLTAGE_RESOLUTION, MQ135_ADC_BIT_RESOLUTION, AIR_PIN, "MQ-135");

BLEServer* pServer = NULL;
BLECharacteristic* pDataChar = NULL;

bool deviceConnected = false;
unsigned long lastReadingTime = 0;

// ============== BLE CALLBACKS ==============

class ServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
        deviceConnected = true;
        Serial.println("Client connected");
        digitalWrite(LED_PIN, HIGH);
    }

    void onDisconnect(BLEServer* pServer) {
        deviceConnected = false;
        Serial.println("Client disconnected");
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
        Serial.println("Found");
    } else {
        Serial.println("Not found");
    }

    // Initialise MQ-135 Air Quality Sensor
    Serial.print("MQ-135 sensor: ");
    MQ135.setRegressionMethod(1); // PPM = a*ratio^b
    MQ135.setA(110.47);            // For CO2
    MQ135.setB(-2.862);            // For CO2
    MQ135.setR0(MQ135_RL_VALUE);   // Set load resistance

    MQ135.init();

    // Calibration (optional - uncomment if you want to calibrate in clean air)
    // Serial.print("Calibrating MQ-135 (ensure clean air)... ");
    // float calcR0 = 0;
    // for(int i = 1; i <= 10; i++) {
    //     MQ135.update();
    //     calcR0 += MQ135.calibrate(MQ135_RATIO_CLEAN_AIR);
    // }
    // MQ135.setR0(calcR0/10);
    // Serial.println("Done");

    Serial.println("Initialized");

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
    
    Serial.println("Advertising");
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
    
    // Read Air Quality (MQ-135) using MQUnifiedsensor
    MQ135.update();  // Update sensor readings
    float co2_ppm = MQ135.readSensor();  // Read CO2 in PPM

    // Convert PPM to air quality index (0-100)
    // Good air: 400-1000 PPM CO2
    // Poor air: 1000-5000 PPM CO2
    float airIndex = map(constrain(co2_ppm, 400, 5000), 400, 5000, 0, 100);

    doc["air_quality"] = (int)airIndex;
    doc["air_ppm"] = round(co2_ppm * 10) / 10.0;  // CO2 in PPM
    doc["air_raw"] = MQ135.getVoltage();          // Voltage reading
    
    // Serialise to JSON
    String payload;
    serializeJson(doc, payload);
    
    // Print to Serial
    Serial.println("Sensor Reading:");
    Serial.printf("   Temp: %.1f°C, Humidity: %.1f%%\n",
                  doc["temperature"].as<float>(),
                  doc["humidity"].as<float>());
    Serial.printf("   Light: %d%%, Soil: %d%%\n",
                  doc["light"].as<int>(),
                  doc["soil"].as<int>());
    Serial.printf("   Air Quality: %d (CO2: %.1f PPM)\n",
                  doc["air_quality"].as<int>(),
                  doc["air_ppm"].as<float>());
    
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
