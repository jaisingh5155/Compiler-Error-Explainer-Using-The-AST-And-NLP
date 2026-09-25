#include <vector>
int main() {
    std::vector<int> packetQueue = {1, 2, 3};
    for (size_t i = 0; i < packetQueue.size(); ++i) {
        accumulator += packetQueue[i];
    }
    return 0;
}
