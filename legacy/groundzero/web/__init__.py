"""
GroundZero — browser-based UI package.

Start the web UI with groundzero_web.py, python -m groundzero.web, or groundzero-web.
(redfish_web.py is also supported as a backward-compat shim).
Nothing in this package imports Tkinter.
"""
def main(*args, **kwargs):
    from groundzero.web.server import main as _server_main
    return _server_main(*args, **kwargs)

__all__ = ["main"]
