/* run.config
   DEPS: fundef_f.h
*/
#include "fundef_f.h"

static int g;

void main() {
    g = bar() + foo();
    write(g);
    return 0;
}