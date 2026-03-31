typedef struct A {int x; int y;} A;

int foo(int *p) {
    return *p+1;
}

int *bar() {
    return 33; //ptr literal
}

void main() {

    int *p = 0x34; //ptr literal
    p = 33; //ptr literal
    int *q; 
    q = 0x2; //ptr literal
    q = foo(30); //ptr literal
    p = bar();

    float *fp;
    fp = 9999; //ptr literal

    A *a;
    a = 0x22; //ptr literal

}