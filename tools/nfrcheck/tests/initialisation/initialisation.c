/* run.config
   DEPS: initialisation.is
   STDOPT: +"-nfr-ispec" +"initialisation.is"
*/


static int g;
static int g1;
static int g2 = 44;
static int output;

void f_init() {
    g = 32;
    g1 = 44;
}

void f_10ms() {
    int x = g + g2; 
    output = x;
}   


void f_close() {
    g2 = g + output + g1;
}