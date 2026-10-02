"""Protected behavioral checks for panel-f3."""

import shutil
import subprocess
from pathlib import Path

p = Path("benchmark-protected.ts")
p.write_text(
    'import assert from "node:assert/strict"; import {format} from "./index.ts"; import {transform} from "./impl.ts"; assert.equal(format("mixed"),"MIXED");assert.equal(format("mixed",{},"!"),"MIXED!");assert.equal(format("MiXeD",{mode:"lower"},"?"),"mixed?");assert.equal(transform("abc",{},"!"),"ABC!");assert.equal(format("abc",{},"end"),"ABCend");assert.equal(transform("abc",{enabled:false},"end"),"abcend");'
)
subprocess.run(
    [shutil.which("node") or "node", "--experimental-strip-types", str(p)], check=True
)
