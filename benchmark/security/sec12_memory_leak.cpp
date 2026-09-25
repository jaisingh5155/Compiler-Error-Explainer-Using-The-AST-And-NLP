#include <cstdlib>
#include <cstdio>
int main() {
    for (int i = 0; i < 10; i++) {
        int* p = (int*)malloc(sizeof(int) * 100);
        p[0] = i;
        printf("%d\n", p[0]);
    }
    return 0;
}
