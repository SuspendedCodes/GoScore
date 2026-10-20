#!/usr/bin/env python3
"""GoScore - start the scoring + broadcast server.

    python run.py                      # http://localhost:8000
    python run.py --port 8080 --pin 4821

Needs only Python 3.8+ (standard library). No pip install.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from goscore.server import make_server, local_ips  # noqa: E402


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="GoScore server")
    ap.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = reachable from other devices on your network")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--data", default=os.path.join(here, "data"), help="where matches/backups are stored")
    ap.add_argument("--output", default=os.path.join(here, "output"), help="where OBS data files are written")
    ap.add_argument("--pin", default=None, help="optional PIN required for any change (reading stays open for overlays)")
    a = ap.parse_args()
    srv, app = make_server(a.host, a.port, a.data, a.output, a.pin)
    print("=" * 62)
    from goscore import __version__
    print(f" GoScore v{__version__} is running")
    print(f"   On this computer : http://localhost:{a.port}/")
    for ip in local_ips():
        print(f"   On your network  : http://{ip}:{a.port}/")
    print(f"   Match data       : {os.path.abspath(a.data)}")
    print(f"   OBS data files   : {os.path.abspath(a.output)}/live/")
    print(f"   PIN protection   : {'ON' if a.pin else 'off'}")
    print("   Stop with Ctrl+C")
    print("=" * 62)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop.set()
        srv.server_close()


if __name__ == "__main__":
    main()
