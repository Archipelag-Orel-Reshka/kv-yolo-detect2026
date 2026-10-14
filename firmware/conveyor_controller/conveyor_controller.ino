#include <DxlMaster2.h>
#include "control.h"

constexpr uint8_t MOTOR_ID = 22;
constexpr unsigned long USB_BAUD = 115200;
constexpr uint32_t BAUDS[] = {1000000, 57600, 115200, 9600, 19200,
                             38400, 250000, 500000, 2000000};
enum MotorKind : uint8_t { UNKNOWN, AX12, MX64, XL320, XL430 };
MotorKind kind = UNKNOWN;
uint8_t protocol = 0;
uint16_t modelNumber = 0;
uint32_t motorBaud = 0;
bool found = false, initialized = false, running = false, stopPending = false;
int16_t requestedSpeed = 0;
uint32_t lastHeartbeat = 0, lastCheck = 0;
char line[32];
uint8_t lineLength = 0;
bool overflow = false;

template <typename T> bool readRegister(uint16_t address, T &value) {
  return DxlMaster.read(protocol, MOTOR_ID, address, value, 2) == DYN_STATUS_OK;
}

template <typename T> bool writeVerified(uint16_t address, T value) {
  // Ignore write replies, then read back. Works with SRL=1 and SRL=2.
  DxlMaster.write(protocol, MOTOR_ID, address, value, 0);
  delay(5);
  T actual = 0;
  return readRegister(address, actual) && actual == value;
}

uint16_t torqueAddress() { return kind == XL430 ? 64 : 24; }

bool writeSpeed(int16_t speed) {
  if (kind == XL430) return writeVerified<int32_t>(104, speed);
  return writeVerified<uint16_t>(32, wheelSpeed(speed));
}

bool stopMotor() {
  running = false;
  requestedSpeed = 0;
  if (!found || kind == UNKNOWN) { stopPending = false; return !found; }
  // Disable torque even if the speed write or read fails.
  const bool torqueOff = writeVerified<uint8_t>(torqueAddress(), 0);
  // In joint mode, legacy Moving Speed=0 means maximum speed. Do not write
  // it until torque-off is confirmed, including before the first INIT.
  const bool zeroSpeed = torqueOff && writeSpeed(0);
  stopPending = !(torqueOff && zeroSpeed);
  if (stopPending) initialized = false;
  return !stopPending;
}

void printStatus() {
  Serial.print(F("STATUS {\"id\":22,\"found\":"));
  Serial.print(found ? F("true") : F("false"));
  Serial.print(F(",\"model\":")); Serial.print(modelNumber);
  Serial.print(F(",\"protocol\":")); Serial.print(protocol);
  Serial.print(F(",\"baud\":")); Serial.print(motorBaud);
  Serial.print(F(",\"supported\":")); Serial.print(kind != UNKNOWN ? F("true") : F("false"));
  Serial.print(F(",\"initialized\":")); Serial.print(initialized ? F("true") : F("false"));
  Serial.print(F(",\"running\":")); Serial.print(running ? F("true") : F("false"));
  Serial.print(F(",\"stop_pending\":")); Serial.print(stopPending ? F("true") : F("false"));
  Serial.print(F(",\"speed\":")); Serial.print(requestedSpeed);
  Serial.println(F("}"));
}

void scanMotor() {
  // Do not discard a failed stop to scan another bus configuration.
  if ((running || stopPending) && !stopMotor()) {
    Serial.println(F("ERR SCAN STOP_FAILED")); return;
  }
  found = initialized = false;
  kind = UNKNOWN; modelNumber = protocol = motorBaud = 0;
  for (uint8_t b = 0; b < sizeof(BAUDS) / sizeof(BAUDS[0]); ++b) {
    DxlMaster.begin(BAUDS[b]);
    DxlMaster.setTimeOut(10);
    for (uint8_t p = 1; p <= 2; ++p) {
      if (DxlMaster.ping(p, MOTOR_ID) != DYN_STATUS_OK) continue;
      protocol = p;
      uint16_t detected = 0;
      if (!readRegister(0, detected)) continue;
      modelNumber = detected; motorBaud = BAUDS[b]; found = true;
      // Only control tables checked against ROBOTIS documentation are allowed.
      if (p == 1 && detected == 12) kind = AX12;
      if (p == 1 && detected == 310) kind = MX64;
      if (p == 2 && detected == 350) kind = XL320;
      if (p == 2 && detected == 1060) kind = XL430;
      if (kind != UNKNOWN) stopMotor();
      printStatus(); return;
    }
  }
  protocol = 0;
  Serial.println(F("ERR SCAN MOTOR_NOT_FOUND"));
  printStatus();
}

bool initializeMotor() {
  if (!found || kind == UNKNOWN || !stopMotor()) return false;
  if (kind == AX12 || kind == MX64) {
    if (kind == MX64) {
      uint8_t torqueMode = 0;
      if (!readRegister(70, torqueMode)) return false;
      if (torqueMode != 0 && !writeVerified<uint8_t>(70, 0)) return false;
    }
    uint16_t cw = 0, ccw = 0;
    if (!readRegister(6, cw) || !readRegister(8, ccw)) return false;
    // Avoid unnecessary EEPROM writes on each start.
    if (cw != 0 && !writeVerified<uint16_t>(6, 0)) return false;
    if (ccw != 0 && !writeVerified<uint16_t>(8, 0)) return false;
  } else {
    uint8_t mode = 0;
    if (!readRegister(11, mode)) return false;
    if (mode != 1 && !writeVerified<uint8_t>(11, 1)) return false;
  }
  initialized = writeSpeed(0);
  return initialized;
}

void discoverDevices() {
  if (running || stopPending) {
    Serial.println(F("ERR DISCOVER MUST_BE_STOPPED")); return;
  }
  // Read-only search, including IDs other than the expected belt motor.
  for (uint8_t b = 0; b < sizeof(BAUDS) / sizeof(BAUDS[0]); ++b) {
    DxlMaster.begin(BAUDS[b]);
    DxlMaster.setTimeOut(3);
    Serial.print(F("BUS ")); Serial.println(BAUDS[b]);
    for (uint16_t id = 0; id <= 252; ++id) {
      for (uint8_t p = 1; p <= 2; ++p) {
        if (DxlMaster.ping(p, id) != DYN_STATUS_OK) continue;
        uint16_t detected = 0;
        if (DxlMaster.read(p, id, 0, detected, 2) != DYN_STATUS_OK) continue;
        Serial.print(F("DEVICE {\"id\":")); Serial.print(id);
        Serial.print(F(",\"model\":")); Serial.print(detected);
        Serial.print(F(",\"protocol\":")); Serial.print(p);
        Serial.print(F(",\"baud\":")); Serial.print(BAUDS[b]);
        Serial.println(F("}"));
      }
    }
  }
  DxlMaster.begin(motorBaud ? motorBaud : BAUDS[0]);
  DxlMaster.setTimeOut(10);
  Serial.println(F("OK DISCOVER"));
}

void faultStop(const __FlashStringHelper *reason) {
  initialized = false;
  stopMotor();
  Serial.print(F("ERR ")); Serial.println(reason);
  printStatus();
}

void handleCommand(char *command) {
  if (!strcmp(command, "STATUS")) { printStatus(); return; }
  if (!strcmp(command, "PING")) {
    lastHeartbeat = millis(); Serial.println(F("OK PING")); return;
  }
  if (!strcmp(command, "STOP")) {
    const bool stopped = stopMotor();
    Serial.println(stopped ? F("OK STOP") : F("ERR STOP FAILED"));
    printStatus(); return;
  }
  if (!strcmp(command, "SCAN")) { scanMotor(); return; }
  if (!strcmp(command, "DISCOVER")) { discoverDevices(); return; }
  if (!strcmp(command, "INIT")) {
    if (running) { Serial.println(F("ERR INIT RUNNING")); return; }
    initialized = false;
    Serial.println(initializeMotor() ? F("OK INIT") : F("ERR INIT FAILED_OR_UNSUPPORTED"));
    printStatus(); return;
  }
  if (!strncmp(command, "START ", 6)) {
    int16_t speed = 0;
    if (!parseSpeed(command + 6, speed)) {
      Serial.println(F("ERR START SPEED_RANGE_1_TO_300")); return;
    }
    if (!initialized || stopPending) { Serial.println(F("ERR START NEED_INIT")); return; }
    if (!stopMotor()) { faultStop(F("START STOP_FAILED")); return; }
    // Preload goal with torque off. No stale goal is applied on enable.
    if (!writeSpeed(speed) || !writeVerified<uint8_t>(torqueAddress(), 1)) {
      faultStop(F("START WRITE_FAILED")); return;
    }
    requestedSpeed = speed; running = true; lastHeartbeat = millis();
    Serial.println(F("OK START")); printStatus(); return;
  }
  Serial.println(F("ERR UNKNOWN_COMMAND"));
}

void setup() {
  Serial.begin(USB_BAUD);
  Serial.println(F("READY KV_CONVEYOR_V1"));
  scanMotor();  // No torque enable and no mode/EEPROM changes at startup.
}

void loop() {
  // Check before processing serial input so a late PING cannot revive motion.
  if (running && hostExpired(millis(), lastHeartbeat)) faultStop(F("HOST_TIMEOUT"));
  for (uint8_t n = 0; n < 64 && Serial.available(); ++n) {
    const char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (overflow) Serial.println(F("ERR LINE_TOO_LONG"));
      else if (lineLength) { line[lineLength] = '\0'; handleCommand(line); }
      lineLength = 0; overflow = false;
    } else if (!overflow) {
      if (lineLength < sizeof(line) - 1) line[lineLength++] = c;
      else overflow = true;
    }
  }
  if (millis() - lastCheck >= 100) {
    lastCheck = millis();
    if (stopPending) stopMotor();
    if (running) {
      uint8_t torque = 0;
      if (!readRegister(torqueAddress(), torque) || torque != 1)
        faultStop(F("MOTOR_LINK_OR_TORQUE"));
    }
  }
}
