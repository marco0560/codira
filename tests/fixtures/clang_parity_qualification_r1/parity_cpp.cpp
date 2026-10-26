#include <cstddef>
#include "parity_cpp.hpp"

namespace parity {

using Count = unsigned int;

enum class Mode {
    Idle = 0,
    Busy = 1
};

/** A record with source-attached documentation. */
struct Box {
    int value;
    Mode mode;

    struct Nested {
        Count size;
    } nested;

    /// Read the stored value.
    int read() const {
        return value;
    }
};

int choose(int value);
double choose(double value);
using IntFunction = int (*)(int);
int global_count = 0;

int choose(int value) {
    return value + 1;
}

double choose(double value) {
    return value + 0.5;
}

int apply(IntFunction function, int value) {
    return function(value);
}

int call_overload(Box& box, int value) {
    return choose(box.read()) + choose(static_cast<double>(value));
}

int call_macro(Box& box, int value) {
    return PARITY_CPP_CALL(choose, box.read()) + value;
}

#define PARITY_CPP_GENERATE(name) int name() { return 42; }
PARITY_CPP_GENERATE(generated_from_macro)

}  // namespace parity
