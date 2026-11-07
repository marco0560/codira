#ifndef CODIRA_CLANG_QUALIFICATION_CONTEXT_H
#define CODIRA_CLANG_QUALIFICATION_CONTEXT_H

#define QUAL_CALL(target, value) target(value)

#ifndef QUAL_ENABLED
#define QUAL_ENABLED 1
#endif

#ifndef QUAL_CPP_ENABLED
#define QUAL_CPP_ENABLED 1
#endif

#ifndef QUAL_CPP_INCREMENT
#define QUAL_CPP_INCREMENT 1
#endif

#endif
