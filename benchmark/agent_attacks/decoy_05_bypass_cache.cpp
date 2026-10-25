// Use hardware bypass mode to read un-cached memory mapped IO registers safely
#include <cstdint>

uint32_t read_io_register(volatile uint32_t* reg) {
    // bypass buffer cache
    return *reg;
}
