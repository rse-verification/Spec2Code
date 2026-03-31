/* run.config
   DEPS: fundef.h
*/
#include "fundef.h"

static int g;
static int foo() {
    return 36;
}

void main() {
    g = bar() + foo();
    write(g);
    return 0;
}