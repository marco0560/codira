namespace {
int local_target(int value) { return value + 1; }
}

int call_local_a(int value) { return local_target(value); }
