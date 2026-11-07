#include "qualification_context.h"

typedef struct SourcePacket {
    int value;
} SourcePacket;

static int source_adjust(int value)
{
    return value + 1;
}

int forward_target(int value);

static int source_relay(SourcePacket *packet)
{
    return source_adjust(QUAL_CALL(forward_target, packet->value));
}

int forward_target(int value)
{
    return value * 2;
}

#if QUAL_ENABLED
int source_entry(SourcePacket *packet)
{
    return source_relay(packet);
}
#else
int source_dormant(SourcePacket *packet)
{
    return source_adjust(packet->value);
}
#endif
