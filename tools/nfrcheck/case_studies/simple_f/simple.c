#include "mod1.h"
#include "mod1.c"
#include "mod2.h"
#include "simple.h"

// g2 and g3 are inputs to next iteration, g, g2 are outputs
static int g;
static int g2;
int g3; 
static int g4;
static int internal_func1(void);
static int internal_func2(void);

static int internal_func1() {
    int x = 32;
    mod1_foo(&x);
    return x + g2 + g3;
}

static int internal_func2() {
    int x = 22;
    mod1_foo(&x);
    return x + g2 + g3;
}

void simp_init() {
    g2 = 42; //weird only g2 here, but for testing purposes
}

void simp_10ms() {
    int (*fun_ptr)(void);
    g = g2 + g4; //g4 only default init
    g3 = read_g3();
    
    if (g > 33) fun_ptr = internal_func1; 
    else fun_ptr = internal_func2;
    
    g2 = fun_ptr();

    int *p;
    p = 0x32;
    g = g + *p;
    
    write_g(g);
    write_g2(g2);
}