#include "Owner.hpp"

int ownership::Owner::read() const {
    return 42;
}

int ownership::invoke(const Owner& owner) {
    return owner.read();
}
