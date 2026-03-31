/* run.config
   DEPS: extern_defs.h callable_spec.is
   STDOPT: +"-nfr-ispec callable_spec.is" 
*/

#include "extern_defs.h"

static void internal_func(void);

void f_10ms() {
    foo();
    int x = bar();
    internal_func();
}