void foo(void);
void bar(void);
void ptr_param_foo(int (*fn)(void));


static void internal_func(void);
static int internal_int_func(void);

static void func_w_int_param(int x);

void main() {
    foo();
    bar();


    
    void (*f_ptr)(void) = internal_func;
    
    
    int (*int_f_ptr)(void) = internal_int_func;
    
    //call to fun ptr
    f_ptr();

    //call with fun call to fun ptr as param
    func_w_int_param(int_f_ptr());
    
    //call with fun ptr as param
    ptr_param_foo(int_f_ptr);
    ptr_param_foo(internal_int_func);

    int x = int_f_ptr();
}