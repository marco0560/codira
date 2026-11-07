#ifndef CODIRA_CLANG_PARITY_OWNER_HPP
#define CODIRA_CLANG_PARITY_OWNER_HPP

namespace ownership {
class Owner {
public:
    int read() const;
};

int invoke(const Owner& owner);
}

#endif
