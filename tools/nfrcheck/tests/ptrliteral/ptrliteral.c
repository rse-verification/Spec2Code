typedef struct A {int x; int y;} A;
int g;
int foo(int *p) {
    return *p+1;
}

int *bar() {
    return &g; //ptr literal
}

void main() {
    int x;

    int *p = &x; //ptr literal
    p = &x; //ptr literal
    int *q; 
    q = &x; //ptr literal
    x = foo(p); //ptr literal
    p = bar();

    float *fp;
    float fpv;
    fp = &fpv; //ptr literal

    A b;
    A *a;
    
    a = &b; //ptr literal

}