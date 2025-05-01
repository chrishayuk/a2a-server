#!/usr/bin/env python3
# a2a_server/main.py
"""
CLI entrypoint for a2a-server: delegates to run.py's run_server.
"""
# a2a imports
from a2a_server.run import run_server

# main entrypoint
def main():
    # call run server
    run_server()

# main entrypoint
def app():
    # call run server
    run_server()

# check for main entrypoint
if __name__ == "__main__":
    # call main
    main()
