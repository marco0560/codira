/* Source-authored C macro declaration qualification fixture. */
#define C_DECLARE_FILE_VARIABLE(name, value) int name = value
#define C_DECLARE_FILE_CONSTANT(name, value) const unsigned int name = value
#define C_DECLARE_LOCAL_VARIABLE(name, value) int name = value

C_DECLARE_FILE_VARIABLE(c_macro_counter, 17);
C_DECLARE_FILE_CONSTANT(c_macro_limit, 23U);

int c_macro_local_probe(void) {
    C_DECLARE_LOCAL_VARIABLE(c_local_counter, 31);
    return c_local_counter;
}
