/* run.config
   DEPS: initialisation.is
   STDOPT: +"-nfr-ispec" +"initialisation.is"
*/

static int g;
static int g2 = 44;
static int output;
static int g4;

void f_init() {
    int x = g;
    g = 32 + g4; //g4 should trigger error
}

void f_10ms() {
    int x = g + g2; 
    g4 = 44; //g4 set here but too late for f_init
    x = output; //output should trigger
}   


void f_close() {
    g2 = g + output; //output should trigger
}