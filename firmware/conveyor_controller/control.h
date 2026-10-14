#pragma once
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

constexpr int16_t MAX_SPEED = 300;
constexpr uint32_t HOST_TIMEOUT_MS = 1000;

inline bool parseSpeed(const char *text, int16_t &speed) {
  if (!text || !*text) return false;
  char *end = nullptr;
  const long value = strtol(text, &end, 10);
  if (*end || value < -MAX_SPEED || value > MAX_SPEED || value == 0) return false;
  speed = static_cast<int16_t>(value);
  return true;
}

inline uint16_t wheelSpeed(int16_t speed) {
  return speed < 0 ? static_cast<uint16_t>(-speed) | 1024U
                   : static_cast<uint16_t>(speed);
}

inline bool hostExpired(uint32_t now, uint32_t last) {
  return static_cast<uint32_t>(now - last) >= HOST_TIMEOUT_MS;
}
