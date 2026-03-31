
typedef struct A {
    int x;
    int y;
} A;

static A a;
static int g2;

void main() {
    g2 = 42;
    a.x = 33;
}