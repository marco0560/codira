namespace alias_case {
double f(double value);
}

#define WRAP(T, N, A) \
    decltype(alias_case::N) impl_##N asm(#N); \
    decltype(alias_case::N) N [[gnu::alias(#N)]]; \
    T impl_##N A

namespace alias_case {
WRAP(double, f, (double value)) { return value + 1.0; }
}
