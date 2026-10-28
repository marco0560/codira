/* Source-authored C++ macro declaration qualification fixture. */
#define CPP_DECLARE_NAMESPACE_VARIABLE(name, value) int name = value
#define CPP_DECLARE_NAMESPACE_CONSTANT(name, value) constexpr int name = value
#define CPP_DECLARE_STATIC_MEMBER(name, value) inline static int name = value;
#define CPP_DECLARE_OUT_OF_LINE_MEMBER(name) static int name;
#define CPP_DECLARE_LOCAL_VARIABLE(name, value) int name = value

namespace macro_context {
CPP_DECLARE_NAMESPACE_VARIABLE(namespace_counter, 17);
CPP_DECLARE_NAMESPACE_CONSTANT(namespace_limit, 23);

struct MacroOwner {
public:
    CPP_DECLARE_STATIC_MEMBER(public_counter, 31)

private:
    CPP_DECLARE_STATIC_MEMBER(secret_counter, 37)

public:
    CPP_DECLARE_OUT_OF_LINE_MEMBER(out_of_line_counter)
};

int MacroOwner::out_of_line_counter = 41;
}  // namespace macro_context

int cpp_macro_local_probe() {
    CPP_DECLARE_LOCAL_VARIABLE(cpp_local_counter, 43);
    return cpp_local_counter;
}
