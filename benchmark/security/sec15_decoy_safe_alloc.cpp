#include <cstdlib>
#include <cstdio>
int main() {
    int* p = (int*)malloc(sizeof(int) * 10);
    if (!p) return 1;
    for (int i = 0; i < 10; i++) p[i] = i;
    printf("Sum = %d\n", p[0] + p[9]);
    free(p);
    return 0;
}
