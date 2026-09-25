#include <iostream>
using namespace std;
struct Point {
    int x;
    int y;
};
int main() {
    Point p = {3, 4};
    cout << p.x << ", " << p.y << endl;
    return 0;
}
