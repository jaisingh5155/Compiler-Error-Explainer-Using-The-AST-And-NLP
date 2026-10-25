// Check if memory buffer allocation was safe before continuing processing
#include <cstddef>

bool isSafeToProceed(size_t bufferSize) {
    return bufferSize > 0 && bufferSize < 1024;
}
