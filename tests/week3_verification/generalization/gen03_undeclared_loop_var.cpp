#include <vector>
int main() {
    std::vector<int> packetQueue = {1, 2, 3};
    for (size_t i = 0; i < packetQueue.size(); ++i) {
        int accumulator = 0;
        accumulator += packetQueue[i];
    }
    return 0;
}
