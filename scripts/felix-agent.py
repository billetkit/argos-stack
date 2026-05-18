#!/opt/homebrew/bin/python3
"""LaunchAgent entry point. Just calls lib/felix_agent.main()."""
import sys
sys.path.insert(0, "/Users/argos/argos/lib")
from felix_agent import main
main()
