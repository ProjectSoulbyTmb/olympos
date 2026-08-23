import socket


class RspsPvpEnv:
    """Drop-in replacement for OsrsPvpEnv that talks to a RelayPlugin running
    inside your own Elvarg-based private server over a line-based TCP protocol.

    Server responses (one line each):
      OK,<reward>,<done>,<o1>,...,<o12>,<m1>,...,<m6>
    """

    def __init__(self, host="127.0.0.1", port=43594, opp_port=None,
                 timeout=10):
        import numpy as np
        self.np = np
        self.host = host
        self.sock = self._connect(host, port, timeout)
        self.opp_sock = (self._connect(host, opp_port, timeout)
                         if opp_port else None)

    @staticmethod
    def _connect(host, port, timeout):
        s = socket.create_connection((host, port), timeout=timeout)
        s.settimeout(timeout)
        return s

    def _recv_line(self, f):
        line = f.readline()
        if not line:
            raise ConnectionError("RSPS relay closed the connection")
        return line.decode().strip()

    def _parse(self, line):
        parts = line.split(",")
        if parts[0] != "OK":
            raise RuntimeError(f"relay error: {line}")
        reward = float(parts[1])
        done = parts[2] == "1"
        obs = self.np.array([float(x) for x in parts[3:15]], dtype=self.np.float32)
        mask = self.np.array([x == "1" for x in parts[15:21]], dtype=bool)
        return obs, mask, reward, done

    def reset(self):
        self.sock.sendall(b"RESET\n")
        obs_a, mask_a, _, _ = self._parse(self._recv_line(
            self.sock.makefile()))
        if self.opp_sock is None:
            return obs_a, obs_a
        obs_b, mask_b, _, _ = self._parse(self._recv_line(
            self.opp_sock.makefile()))
        return obs_a, obs_b

    def legal_mask(self):
        raise NotImplementedError(
            "masks arrive with each step/reset; cache them instead")

    def step(self, act_a, act_b):
        fa = self.sock.makefile()
        self.sock.sendall(f"STEP,{int(act_a)}\n".encode())
        obs_a, mask_a, r_a, done = self._parse(self._recv_line(fa))
        r_b = -r_a
        outcome = 1 if done and r_a > 0 else (2 if done and r_a < 0 else 0)
        return obs_a, obs_a, r_a, r_b, outcome, done

    def close(self):
        try:
            self.sock.sendall(b"CLOSE\n")
            self.sock.close()
            if self.opp_sock:
                self.opp_sock.close()
        except OSError:
            pass
