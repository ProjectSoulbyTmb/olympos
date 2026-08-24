import sys
import time

sys.path.insert(0, r"osrs-llm-agent")
from server.rsps_server import GameServer
from server.client import RemoteGameSDK

srv = GameServer(port=43992)
srv.start_async()
time.sleep(0.8)
a = RemoteGameSDK(name="ta", port=srv.port, channel="main")
b = RemoteGameSDK(name="tb", port=srv.port, channel="main")

st = a._request({"cmd": "status"})["status"]
assert "ta" in st["players"] and "tb" in st["players"], st
print("status players:", sorted(st["players"]), "trades:", st["trades_active"])

a._request({"cmd": "trade_offer", "target": "tb"})
r = b._request({"cmd": "state"})
notices = r.get("notices", [])
assert any(n["type"] == "trade_invite" and n["from"] == "ta"
           for n in notices), notices
print("invite delivered:", notices[0]["type"])

b._request({"cmd": "trade_accept"})
a._call("walk", "tree_1")
for _ in range(10):
    try:
        a._call("chop")
    except Exception:
        break
inv = a.inventory()
assert inv.get("logs", 0) >= 1, inv
n_logs = min(3, inv["logs"])
r1 = a._request({"cmd": "trade_add", "item": "logs", "n": n_logs})
assert r1["ok"], r1
view = a._request({"cmd": "state"}).get("trade")
assert view["my_offer"]["logs"] == n_logs, view

# bob confirms first - trade must NOT execute until alice also does
b._request({"cmd": "trade_confirm"})
mid = a.inventory()
assert mid.get("logs") == n_logs, "executed early!"
r = a._request({"cmd": "trade_confirm"})
assert r["ok"], r
print("executed:", r.get("result"))

sa = a.inventory()
sb = b.inventory()
assert sa.get("logs", 0) == inv["logs"] - n_logs, sa
assert sb.get("logs") == n_logs, sb
assert not a._request({"cmd": "state"}).get("trade"), "trade still open"

# cancel path
a._request({"cmd": "trade_offer", "target": "tb"})
b._request({"cmd": "trade_accept"})
a._request({"cmd": "trade_add_coins", "n": 10})
b._request({"cmd": "trade_cancel"})
assert not a._request({"cmd": "state"}).get("trade")

a.close(); b.close(); srv.running = False
print("TRADE SYSTEM OK")
