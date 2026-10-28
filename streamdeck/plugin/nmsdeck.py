#!/usr/bin/env python3
"""OpenDeck plugin: the No Man's Sky keys follow the game.

Every key on the NMS profile is an instance of com.bob.nmsdeck.key with a
`slot` setting (0-14). The plugin draws the slot for the current page and,
while a key is held, holds the game key down with xdotool (XTest, which reaches
the game through XWayland). The page follows /api/mode on the exporter (ship,
exocraft or on foot); the arrow keys page by hand until the mode next changes.

pages.json, written by scripts/nms-streamdeck install, holds the pages; this
file is standard library only. Started by OpenDeck as
    nmsdeck.py -port P -pluginUUID U -registerEvent E -info JSON
"""
import base64
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
POLL_S = 0.5
SETTLE = 2  # polls a new mode must last before the page follows (skips transitions)
XKEY = {"space": "space", "ctrl": "Control_L", "alt": "Alt_L", ",": "comma", ".": "period", "/": "slash"}


class WebSocket:
    """Just enough of RFC 6455 for a client on localhost: text frames, ping, close."""

    def __init__(self, port: int):
        self.sock = socket.create_connection(("127.0.0.1", port))
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                           "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1)
            if not chunk:
                raise ConnectionError("closed during handshake")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError(head.decode(errors="replace"))
        self.lock = threading.Lock()

    def _frame(self, opcode: int, data: bytes) -> None:
        n = len(data)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        with self.lock:
            self.sock.sendall(head + mask + body)

    def send(self, obj: dict) -> None:
        self._frame(0x1, json.dumps(obj).encode())

    def _read(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return buf

    def recv(self) -> dict | None:
        """The next text message as JSON; None for the close frame."""
        data = b""
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)
            opcode = b0 & 0x0F
            if opcode == 0x8:
                return None
            if opcode == 0x9:
                self._frame(0xA, payload)
                continue
            if opcode in (0x0, 0x1):
                data += payload
                if b0 & 0x80:
                    return json.loads(data)


class Deck:
    def __init__(self, ws: WebSocket, config: dict):
        self.ws, self.config = ws, config
        self.order = config["order"]
        self.page = self.order[0]
        self.contexts: dict[str, int] = {}     # context -> slot
        self.held: dict[str, str] = {}         # context -> X key held down
        self.images: dict[str, str] = {}
        self.lock = threading.RLock()  # the event loop and the mode poller both draw

    def image(self, rel: str) -> str:
        if rel not in self.images:
            with open(os.path.join(HERE, rel), "rb") as f:
                self.images[rel] = "data:image/png;base64," + base64.b64encode(f.read()).decode()
        return self.images[rel]

    def slot(self, n: int) -> dict | None:
        keys = self.config["pages"][self.page]["keys"]
        return keys[n] if 0 <= n < len(keys) else None

    def draw(self, context: str) -> None:
        key = self.slot(self.contexts[context])
        image = self.image(key["image"]) if key else ""
        self.ws.send({"event": "setImage", "context": context, "payload": {"image": image, "target": 0}})

    def show(self, page: str) -> None:
        with self.lock:
            if page == self.page:
                return
            self.page = page
            for context in self.contexts:
                self.draw(context)

    def on(self, msg: dict) -> None:
        with self.lock:
            self._on(msg)

    def _on(self, msg: dict) -> None:
        event, context = msg.get("event"), msg.get("context")
        if event == "willAppear":
            self.contexts[context] = int(msg["payload"]["settings"].get("slot", -1))
            self.draw(context)
        elif event == "willDisappear":
            self.contexts.pop(context, None)
            self.release(context)
        elif event == "keyDown" and context in self.contexts:
            key = self.slot(self.contexts[context])
            if key and "key" in key:
                x = XKEY.get(key["key"], key["key"])
                self.held[context] = x
                subprocess.run(["xdotool", "keydown", x])
        elif event == "keyUp" and context in self.contexts:
            key = self.slot(self.contexts[context])
            if context in self.held:
                self.release(context)
            elif key and "nav" in key:
                i = self.order.index(self.page)
                self.show(self.order[(i + key["nav"]) % len(self.order)])

    def release(self, context: str) -> None:
        x = self.held.pop(context, None)
        if x:
            subprocess.run(["xdotool", "keyup", x])


def follow(deck: Deck, url: str) -> None:
    """Page to the game's mode whenever it changes (and has lasted SETTLE polls)."""
    seen, count, followed = None, 0, None
    while True:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                mode = json.loads(r.read()).get("mode")
        except (OSError, ValueError):
            mode = None
        count = count + 1 if mode == seen else 1
        seen = mode
        if mode in deck.order and count >= SETTLE and mode != followed:
            followed = mode
            deck.show(mode)
        time.sleep(POLL_S)


def main() -> None:
    args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
    with open(os.path.join(HERE, "pages.json")) as f:
        config = json.load(f)
    ws = WebSocket(int(args["-port"]))
    ws.send({"event": args["-registerEvent"], "uuid": args["-pluginUUID"]})
    deck = Deck(ws, config)
    threading.Thread(target=follow, args=(deck, config["mode_url"]), daemon=True).start()
    while (msg := ws.recv()) is not None:
        try:
            deck.on(msg)
        except Exception as e:  # one bad event must not take the deck down
            print(f"nmsdeck: {msg.get('event')}: {e!r}", file=sys.stderr)


if __name__ == "__main__":
    main()
