#include <vector>
#include <numeric>

int sum_vector(std::vector<int> data) {
    return std::accumulate(data.begin(), data.end(), 0);
}

int main() {
    std::vector<int> v = {1, 2, 3};
    return sum_vector(v);
}
