typedef struct A {
    int x;
    int y;
} A;

A a;
int g;
static int g2;

void main() {

    g2 = g;
    a.x = 33;
}