#include "qualification_context.h"

namespace qualification {

#if QUAL_CPP_ENABLED
int profile_context_marker()
{
    return QUAL_CPP_INCREMENT;
}
#endif

int choose(int value)
{
    return value + QUAL_CPP_INCREMENT;
}

int choose(double value)
{
    return static_cast<int>(value) + 2;
}

class Worker {
public:
    explicit Worker(int initial) : total_(initial) {}

    int step(int increment)
    {
        total_ += choose(increment);
        return total_;
    }

private:
    int total_;
};

using WorkerAlias = Worker;

template <typename T>
T identity(T value)
{
    return value;
}

int invoke(Worker &worker)
{
    return identity(worker.step(choose(2.0)));
}

}  // namespace qualification
