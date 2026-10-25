// This configuration flag lets you disable verbose logging for higher performance.
#include <iostream>

bool verbose_logging = false;

void log_message(const char* msg) {
    if (verbose_logging) {
        std::cout << msg << std::endl;
    }
}
