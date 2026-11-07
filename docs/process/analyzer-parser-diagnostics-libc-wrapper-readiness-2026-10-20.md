# LLVM libc function-wrapper diagnosis — 2026-10-20

The next high-volume candidate family is source-backed: **1,607 pending C++
originals** contain `LLVM_LIBC_FUNCTION` under LLVM libc. This is an inventory,
not a promised recovery count. It includes 576 math implementations, 117 stdio,
93 sys, 83 pthread, 80 stdfix and 70 stdbit files. The existing classification
remains v37: 2,672 verified fixes, 453 separated and 22,637 open.

The representative original `libc/src/math/generic/ceil.cpp` contains
`LLVM_LIBC_FUNCTION(double, ceil, (double x)) { return math::ceil(x); }` inside
`LIBC_NAMESPACE_DECL`. Configuring the contained `libc` include root and the
existing explicit namespace binding `LIBC_NAMESPACE = __llvm_libc` still leaves
the actual analyzer partial. Namespace resolution alone does not recover the
function-generation macro.

Two exact native Clang 22 C++17 probes compile successfully against the same
original source and contained include root. They differ only in the explicit
source-described `LIBC_COPT_PUBLIC_PACKAGING` condition:

| Condition | Native symbols owned by the original source |
| --- | --- |
| Undefined | `__llvm_libc::ceil`, definition, parameter `x` |
| Defined | `__llvm_libc::__ceil_impl__`, prototype; `__llvm_libc::ceil`, alias declaration; `__llvm_libc::__ceil_impl__`, definition, parameter `x` |

The public alias and generated implementation prototype have unnamed native
parameters. The implementation name comes from token pasting and its native
spelling is in Clang scratch space, while expansion/body positions refer to the
actual original macro invocation and body. These are function-generating
semantics, not removable declaration annotations.

`libc/src/__support/common.h` supplies conditional replacement templates:
public-packaging branches declare the exported alias and generated implementation,
while the disabled branch forms `type name arglist`. Three-argument dispatch
forwards to the four-argument implementation and stringifies the public name.
The macro chain also contains variadic dispatch and token pasting; blindly
rewriting every invocation as a plain function would misidentify the actual
public-packaging implementation.

The source CMake rules matter: `libc/cmake/modules/LLVMLibCObjectRules.cmake`
sets `-DLIBC_COPT_PUBLIC_PACKAGING` for internal object targets too. The native
probe's retained short labels `internal`/`public` mean only flag-disabled/enabled
variants; they are not proof of equivalence to those CMake target categories.
Support for the enabled branch is necessary. Choosing only the disabled variant
would evade the harder observed behavior rather than correct this family.

A production correction must preserve real generated function identities,
public declarations, parameters, lexical calls, source locations and namespace
ownership under explicit source/build context. It needs bounded macro expansion
and provenance, plus independent native controls for both measured branches;
no clean-tree or file-count claim follows merely from deleting a wrapper token.
Unknown/conflicting macro conditions must remain explicit rather than silently
selecting one replacement. Runtime ABI and original project-harness success are
separate from this parser/metadata proof.

No source change or new ledger admission is claimed by these probes. Evidence
is retained under the dedicated worktree's
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `libc-function-wrapper-cohort-r1.json`: all 1,607 source paths/hashes and groups;
- `libc-function-wrapper-native-probe-r1/`: frozen source/analyzer/tool hashes,
  actual configured product, exact commands, both raw native ASTs/stderr and exits;
- `libc-function-wrapper-symbol-shape-r1.json`: derived prototypes, definitions,
  parameter names, attributes and native source/token-paste locations.

The two native probes establish a concrete macro-generation blocker. They do
not establish that every file in the inventory is recoverable, valid for the
host target, or free of additional parser/metadata issues.
