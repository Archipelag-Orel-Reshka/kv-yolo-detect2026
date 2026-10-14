#pragma once
#include <cstdint>
#include <deque>
#include <map>
#include <sstream>
#include <string>

using __FlashStringHelper = char;
#define F(value) value
constexpr uint8_t DYN_STATUS_OK = 0;
extern uint32_t testTime;
inline uint32_t millis() { return testTime; }
inline void delay(uint32_t duration) { testTime += duration; }

struct FakeSerial {
  std::deque<char> input;
  std::ostringstream output;
  void begin(unsigned long) {}
  int available() { return input.size(); }
  char read() { char c = input.front(); input.pop_front(); return c; }
  template<class T> void print(T value) { output << +value; }
  void print(const char *value) { output << value; }
  template<class T> void println(T value) { print(value); output << '\n'; }
  void inject(const std::string &text) { for (char c : text) input.push_back(c); }
};
extern FakeSerial Serial;

struct FakeMaster {
  uint32_t baud = 0;
  uint8_t expectedProtocol = 1;
  uint16_t expectedModel = 12;
  bool failRead = false;
  bool ignoreWrite = false;
  bool present = true;
  std::map<uint16_t, int32_t> registers;
  unsigned modeWrites = 0;
  void begin(uint32_t rate) { baud = rate; }
  void setTimeOut(uint16_t) {}
  uint8_t ping(uint8_t proto, uint8_t id) {
    return present && baud == 1000000 && proto == expectedProtocol && id == 22 ? 0 : 1;
  }
  template<class T> uint8_t read(uint8_t, uint8_t, uint16_t address, T &data, uint8_t) {
    if (failRead || !present) return 1;
    data = address == 0 ? expectedModel : registers[address];
    return 0;
  }
  template<class T> uint8_t write(uint8_t, uint8_t, uint16_t address, T data, uint8_t) {
    if (!ignoreWrite && present) {
      registers[address] = data;
      if (address == 6 || address == 8 || address == 11) ++modeWrites;
    }
    return 0;
  }
};
extern FakeMaster DxlMaster;
