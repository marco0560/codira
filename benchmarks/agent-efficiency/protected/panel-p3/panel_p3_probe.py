"""Protected behavioral checks for panel-p3."""

import shutil
import subprocess
from pathlib import Path

p = Path("store/benchmark_protected_test.go")
p.write_text(
    'package store\nimport ("testing"; "example.org/codira-benchmark-service/config")\nfunc TestBenchmarkProtected(t *testing.T) { for _, v := range []string{"", "mixed"} { r,e:=Format(v,config.Config{Limit:0,Mode:"upper"}); if e!=nil || r!=strings.ToUpper(v) { t.Fatal(r,e) } }; if _,e:=Format("a",config.Config{Limit:-1});e==nil {t.Fatal("negative accepted")}; r,e:=Format("ABCDE",config.Config{Limit:2,Mode:"lower"});if e!=nil||r!="ab" {t.Fatal(r,e)} }\n'.replace(
        '"testing";', '"testing"; "strings";'
    )
)
subprocess.run([shutil.which("go") or "go", "test", "./..."], check=True)
