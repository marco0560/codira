static int local_value(int value) {
    return value + 2;
}

int use_local_b(void) {
    return local_value(2);
}
