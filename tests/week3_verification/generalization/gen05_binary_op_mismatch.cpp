struct AudioSample {
    float amplitude;
};
int main() {
    AudioSample s1{0.5f};
    AudioSample s2{0.8f};
    auto result = s1 + s2;
    return 0;
}
