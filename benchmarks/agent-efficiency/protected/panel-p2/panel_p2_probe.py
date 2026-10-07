"""Protected behavioral checks for panel-p2."""

import shutil
import subprocess

program = r"""const assert=require('node:assert/strict'); const picomatch=require('./'); let events=[]; const match=picomatch('*.js',{ignore:'skip.js',onResult:()=>events.push('result'),onIgnore:()=>events.push('ignore'),onMatch:()=>events.push('match')}); assert.equal(match('skip.js'),false); assert.deepEqual(events,['result','ignore']); events=[]; assert.equal(match('ok.js'),true); assert.deepEqual(events,['result','match']); assert.equal(match('no.txt'),false);"""
subprocess.run([shutil.which("node") or "node", "-e", program], check=True)
