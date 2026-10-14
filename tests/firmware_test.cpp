#include <cassert>
#include "stubs/DxlMaster2.h"
uint32_t testTime = 0;
FakeSerial Serial;
FakeMaster DxlMaster;
#include "../firmware/conveyor_controller/conveyor_controller.ino"

void command(const char *value) {
  Serial.inject(std::string(value) + "\n");
  while (Serial.available()) loop();
}

int main() {
  DxlMaster.registers[8] = 1023;
  setup();
  assert(found && modelNumber == 12 && !running && !initialized);
  assert(DxlMaster.registers[24] == 0 && DxlMaster.registers[32] == 0);
  assert(DxlMaster.modeWrites == 0); // Boot never changes EEPROM.
  command("START 50");
  assert(!running && DxlMaster.registers[24] == 0);
  command("INIT");
  assert(initialized && DxlMaster.registers[8] == 0 && !running);
  unsigned changes = DxlMaster.modeWrites;
  command("INIT");
  assert(changes == DxlMaster.modeWrites);
  command("START -50");
  assert(running && DxlMaster.registers[32] == 1074 && DxlMaster.registers[24] == 1);
  command("STOP");
  assert(!running && DxlMaster.registers[24] == 0 && DxlMaster.registers[32] == 0);
  command("START 50");
  const auto heartbeat = lastHeartbeat;
  command("START 0");
  command("STATUS");
  assert(lastHeartbeat == heartbeat); // Invalid input/status cannot extend lease.
  testTime = heartbeat + 1000;
  command("PING"); // Late heartbeat must not revive a timed-out start.
  assert(!running && !initialized && DxlMaster.registers[24] == 0);
  command("START 50");
  assert(!running);
  command("INIT");
  DxlMaster.ignoreWrite = true;
  command("START 50");
  assert(!running && !initialized); // A write without readback is not success.
  DxlMaster.ignoreWrite = false;
  command("INIT");
  command("START 50");
  DxlMaster.failRead = true;
  command("STOP");
  assert(stopPending && !running && !initialized);
  const auto savedBaud = motorBaud;
  command("SCAN");
  assert(stopPending && found && savedBaud == motorBaud);
  DxlMaster.failRead = false;
  testTime += 100;
  loop();
  assert(!stopPending && DxlMaster.registers[24] == 0);
  command("INIT");
  Serial.inject(std::string(40, 'x') + "START 50\n");
  while (Serial.available()) loop();
  assert(!running); // Overflow drops the entire line, including its suffix.
  DxlMaster.expectedProtocol = 2;
  DxlMaster.expectedModel = 1060;
  command("SCAN");
  command("INIT");
  command("START -50");
  assert(running && DxlMaster.registers[64] == 1 && DxlMaster.registers[104] == -50);
  command("STOP");
  DxlMaster.expectedModel = 350;
  command("SCAN"); command("INIT"); command("START -50");
  assert(running && DxlMaster.registers[24] == 1 && DxlMaster.registers[32] == 1074);
  command("STOP");
  DxlMaster.expectedModel = 999;
  command("SCAN"); command("INIT"); command("START 50");
  assert(found && kind == UNKNOWN && !initialized && !running);
  DxlMaster.present = false;
  command("SCAN"); command("START 50");
  assert(!found && !running);
}
