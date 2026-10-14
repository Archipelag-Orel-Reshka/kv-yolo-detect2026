#include <cassert>
#include "../firmware/conveyor_controller/control.h"

int main() {
  int16_t speed = 0;
  assert(parseSpeed("300", speed) && speed == 300);
  assert(parseSpeed("-300", speed) && speed == -300);
  for (const char *bad : {"", "0", "301", "-301", "50 junk", "garbage", "999999999999999999"})
    assert(!parseSpeed(bad, speed));
  assert(wheelSpeed(-100) == 1124);
  assert(wheelSpeed(100) == 100);
  assert(wheelSpeed(0) == 0);
  assert(!hostExpired(999, 0));
  assert(hostExpired(1000, 0));
  assert(!hostExpired(499, UINT32_MAX - 499));
  assert(hostExpired(500, UINT32_MAX - 499));
}
