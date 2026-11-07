static int local_value(int value) {
    return value + 1;
}

int use_local_a(void) {
    return local_value(1);
}
