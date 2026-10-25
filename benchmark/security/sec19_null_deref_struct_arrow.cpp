#include <iostream>
using namespace std;
struct Point {
    int x;
    int y;
};
int main() {
    Point* pt = nullptr;
    pt->x = 10;
    return 0;
}
