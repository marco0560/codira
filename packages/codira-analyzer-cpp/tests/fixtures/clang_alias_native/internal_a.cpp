static int header_local(void) { return 1; }
namespace { int anonymous_collision(void) { return 5; } }
namespace { struct HiddenType {}; }
void unique_external_collision(HiddenType value) { (void)value; }
int external_shared(void) { return 2; }
