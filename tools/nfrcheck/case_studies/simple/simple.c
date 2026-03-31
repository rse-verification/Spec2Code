#include "mod1.h"
#include "mod2.h"
#include "simple.h"

// g2 and g3 are inputs to next iteration, g, g2 are outputs
static int g;
static int g2;
static int g3; 
static int internal_func(void);


static int internal_func() {
    int x = 32;
    mod2_foo(&x);
    return x + g2 + g3;
}

void simp_init() {
    g2 = 42; //weird only g2 here, but for testing purposes
}

void simp_10ms() {
    g = g2;
    g3 = read_g3();

    g2 = internal_func();
    
    write_g(g);
    write_g2(g2);
}