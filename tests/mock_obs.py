"""Tiny obs-websocket v5 mock (no dependencies) to test the control page without OBS.
Implements just the requests GoScore uses, including the real password handshake."""
import asyncio, base64, hashlib, json, struct, threading, os

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class MockObs:
    def __init__(self, port=14455, password="secret", scenes=("CAM1 Wide", "Bowler End", "Batter End", "Replay", "Scorecard", "BRB")):
        self.port, self.password = port, password
        self.scenes = list(scenes)
        self.program, self.preview, self.studio, self.streaming = self.scenes[0], self.scenes[1], False, True
        self.log, self.clients, self.loop, self.ready = [], [], None, threading.Event()
        self.salt, self.challenge = "saltsaltsalt", "challengechallenge"

    # --- ws framing -------------------------------------------------------
    @staticmethod
    def _frame(text):
        b = text.encode(); n = len(b)
        h = bytes([0x81]) + (bytes([n]) if n < 126 else bytes([126]) + struct.pack(">H", n) if n < 65536 else bytes([127]) + struct.pack(">Q", n))
        return h + b

    @staticmethod
    async def _read(r):
        h = await r.readexactly(2); op = h[0] & 15; n = h[1] & 127
        if n == 126: n = struct.unpack(">H", await r.readexactly(2))[0]
        elif n == 127: n = struct.unpack(">Q", await r.readexactly(8))[0]
        mask = await r.readexactly(4) if h[1] & 128 else b"\0\0\0\0"
        data = bytearray(await r.readexactly(n))
        for i in range(n): data[i] ^= mask[i % 4]
        return op, bytes(data)

    async def _send(self, w, obj): w.write(self._frame(json.dumps(obj))); await w.drain()

    async def _broadcast(self, etype, data):
        for w in list(self.clients):
            try: await self._send(w, {"op": 5, "d": {"eventType": etype, "eventIntent": 0, "eventData": data}})
            except Exception: pass

    def _auth_ok(self, given):
        sec = base64.b64encode(hashlib.sha256((self.password + self.salt).encode()).digest()).decode()
        return given == base64.b64encode(hashlib.sha256((sec + self.challenge).encode()).digest()).decode()

    async def _handle(self, r, w):
        try:
            head = (await r.readuntil(b"\r\n\r\n")).decode()
            key = [l.split(": ")[1] for l in head.split("\r\n") if l.lower().startswith("sec-websocket-key")][0]
            acc = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
            w.write(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {acc}\r\n\r\n".encode())
            hello = {"obsWebSocketVersion": "5.5.0", "rpcVersion": 1}
            if self.password: hello["authentication"] = {"challenge": self.challenge, "salt": self.salt}
            await self._send(w, {"op": 0, "d": hello})
            ident = False
            while True:
                op, data = await self._read(r)
                if op == 8: break
                if op != 1: continue
                m = json.loads(data)
                if m["op"] == 1:
                    if self.password and not self._auth_ok(m["d"].get("authentication")):
                        w.write(struct.pack(">BBH", 0x88, 2, 4009)); await w.drain(); break
                    ident = True; self.clients.append(w); await self._send(w, {"op": 2, "d": {"negotiatedRpcVersion": 1}})
                elif m["op"] == 6 and ident:
                    d = m["d"]; t = d["requestType"]; rd = d.get("requestData") or {}; self.log.append((t, rd)); out = {}; ok = True; ev = None
                    if t == "GetSceneList":
                        out = {"currentProgramSceneName": self.program, "currentPreviewSceneName": self.preview if self.studio else None,
                               "scenes": [{"sceneName": s, "sceneIndex": i} for i, s in enumerate(reversed(self.scenes))]}
                    elif t == "SetCurrentProgramScene":
                        if rd["sceneName"] in self.scenes: self.program = rd["sceneName"]; ev = ("CurrentProgramSceneChanged", {"sceneName": self.program})
                        else: ok = False
                    elif t == "SetCurrentPreviewScene":
                        if self.studio and rd["sceneName"] in self.scenes: self.preview = rd["sceneName"]; ev = ("CurrentPreviewSceneChanged", {"sceneName": self.preview})
                        else: ok = False
                    elif t == "GetStudioModeEnabled": out = {"studioModeEnabled": self.studio}
                    elif t == "SetStudioModeEnabled": self.studio = rd["studioModeEnabled"]; ev = ("StudioModeStateChanged", {"studioModeEnabled": self.studio})
                    elif t == "TriggerStudioModeTransition":
                        if self.studio: self.program, self.preview = self.preview, self.program; ev = ("CurrentProgramSceneChanged", {"sceneName": self.program})
                        else: ok = False
                    elif t == "GetStreamStatus": out = {"outputActive": self.streaming}
                    elif t in ("SetCurrentSceneTransition", "SetCurrentSceneTransitionDuration"): pass
                    else: ok = False
                    await self._send(w, {"op": 7, "d": {"requestType": t, "requestId": d["requestId"], "requestStatus": {"result": ok, "code": 100 if ok else 600, "comment": None if ok else "bad request"}, "responseData": out}})
                    if ev: await self._broadcast(*ev)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            if w in self.clients: self.clients.remove(w)
            try: w.close()
            except Exception: pass

    def start(self):
        def run():
            self.loop = asyncio.new_event_loop(); asyncio.set_event_loop(self.loop)
            srv = self.loop.run_until_complete(asyncio.start_server(self._handle, "127.0.0.1", self.port))
            self.ready.set(); self.loop.run_forever()
        threading.Thread(target=run, daemon=True).start(); self.ready.wait(5); return self

    def external_switch(self, name):           # someone clicks in OBS itself
        self.program = name
        asyncio.run_coroutine_threadsafe(self._broadcast("CurrentProgramSceneChanged", {"sceneName": name}), self.loop)
