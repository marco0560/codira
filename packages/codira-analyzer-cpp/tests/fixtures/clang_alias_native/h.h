#ifndef H
#define H
#if PUBLIC
#define WRAP(T,N,A) decltype(NS::N) impl_##N asm(#N); decltype(NS::N) N [[gnu::alias(#N)]]; T impl_##N A
#else
#define WRAP(T,N,A) T N A
#endif
namespace NS { double f(double x); double target(double x); }
#endif
