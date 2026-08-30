import subprocess
import os

os.chdir(r"C:\Users\Nguyen Cong Thong\Desktop\AI attendance\figma")

result = subprocess.run(['pnpm', 'exec', 'tsc', '--noEmit'], capture_output=True, text=True, timeout=60, shell=True)
print('STDOUT:', result.stdout)
print('STDERR:', result.stderr)
print('Return code:', result.returncode)