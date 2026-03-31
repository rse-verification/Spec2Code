/* run.config
   DEPS: entry_f_spec.is entry_f.h
   STDOPT: +"-nfr-ispec entry_f_spec.is"
*/
/*This test should warn that entry_f.h declares entry point f_bar, which is not in the ispec*/
#include "entry_f.h"

int f_util(int x) {
   return x + 1;
}

void f_init() {
   int g = f_util(3);
}
