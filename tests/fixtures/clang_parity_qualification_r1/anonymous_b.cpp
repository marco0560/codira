namespace {
int local_target(int value) { return value + 2; }
}

int call_local_b(int value) { return local_target(value); }
