import streamlit as st
try:
    from streamlit.runtime.scriptrunner import get_script_run_ctx
except ImportError:
    from streamlit.scriptrunner import get_script_run_ctx

print(f"CTX: {get_script_run_ctx()}")
if __name__ == "__main__":
    pass
