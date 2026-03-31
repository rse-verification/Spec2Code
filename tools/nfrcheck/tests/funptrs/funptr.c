void foo(void);
void bar(void);

static void internal_func(void);

void main() {
    foo();
    bar();
    internal_func();
}