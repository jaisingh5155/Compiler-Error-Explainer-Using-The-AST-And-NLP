import sys
import os
import json
import subprocess
import re

sys.path.insert(0, 'src')
from auto_healer import attempt_fix

filename = 'test_heal.cpp'
with open(filename, 'r') as f:
    source = f.read()

def get_errors(fname):
    res = subprocess.run([sys.executable, 'src/main.py', fname, '-j'], capture_output=True, text=True)
    try:
        data = json.loads(res.stdout)
        return data.get('errors', [])
    except:
        return []

current_source = source
max_attempts = 15
for i in range(max_attempts):
    errors = get_errors(filename)
    if not errors:
        break
    
    # Try fixing first error
    err = errors[0]
    patched = attempt_fix(current_source, err)
    if patched and patched != current_source:
        current_source = patched
        with open(filename, 'w') as f:
            f.write(current_source)
    else:
        # If first fails, try others
        fixed = False
        for e in errors[1:]:
            patched = attempt_fix(current_source, e)
            if patched and patched != current_source:
                current_source = patched
                with open(filename, 'w') as f:
                    f.write(current_source)
                fixed = True
                break
        if not fixed:
            break

# Print final source to stdout
print(current_source)
