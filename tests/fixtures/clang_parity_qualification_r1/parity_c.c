#include <stddef.h>
#include "parity_api.h"

#define PARITY_C_SCALE(value) ((value) * 3)
#define PARITY_C_CALL(value) c_internal(value)

typedef enum ParityMode {
    PARITY_IDLE = 0,
    PARITY_BUSY = 1
} ParityMode;

typedef struct ParityRecord {
    int value;
    ParityMode mode;
} ParityRecord;

int c_internal(int value);
int c_external(int value);
int c_count = 0;

/** Add one to the supplied value. */
int c_internal(int value) {
    return value + 1;
}

/** Exercise direct, macro-expanded, and external calls. */
int c_entry(int value) {
    return c_internal(PARITY_C_SCALE(value)) + PARITY_C_CALL(value) + c_external(value);
}

#define PARITY_C_GENERATE(name) int name(void) { return 41; }
PARITY_C_GENERATE(c_generated_from_macro)
