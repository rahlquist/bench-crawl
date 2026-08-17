import subprocess, sys, os
# Harness "exits quickly" but leaves a long-lived grandchild behind.
subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), "_orphan_grandchild.py")])
sys.exit(0)
