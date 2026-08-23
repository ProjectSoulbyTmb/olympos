"""Remote gym server for the PvP environment.

Speaks the exact wire protocol your RspsPvpEnv client (rsps_adapter) and
Elvarg RelayPlugin already speak:
    RESET          -> OK,<reward>,<done>,<o1>..<o12>,<m1>..<m6>
    STEP,<action>  -> same shape (agent A acts; agent B is a bot)
    CLOSE          -> connection closed

Each connection gets its own OsrsPvpEnv session, so train.py-style loops
(or N parallel learners) can drive environments over the network.
"""
import socket
import threading

from envs.osrs_sim import HeuristicBot, N_ACTIONS, OBS_DIM, OsrsPvpEnv, \
    RandomBot


def _format(obs, mask, reward, done):
    o = ",".join(f"{x:.6f}" for x in obs)
    m = ",".join("1" if flag else "0" for flag in mask)
    return f"OK,{reward:.6f},{1 if done else 0},{o},{m}\n"


class _Session:
    def __init__(self, seed, bot_kind="heuristic"):
        self.env = OsrsPvpEnv(seed=seed)
        self.bot_kind = bot_kind
        self.obs_a, self.obs_b = self.env.reset()
        self.last_mask = None

    def reset(self):
        self.obs_a, self.obs_b = self.env.reset()
        return self._masked(self.obs_a)

    def _masked(self, obs):
        import numpy as np
        mask = np.ones(N_ACTIONS, dtype=bool)
        return obs, mask

    def legal_mask_pair(self):
        return self.env.legal_mask()

    def step(self, action):
        action = max(0, min(N_ACTIONS - 1, int(action)))
        if self.bot_kind == "heuristic":
            opponent = HeuristicBot()
        else:
            opponent = RandomBot(action + 7919)
        mask_a, mask_b = self.env.legal_mask()
        opp_act = int(opponent.act(self.obs_b, mask_b))
        next_a, next_b, r_a, r_b, outcome, done = self.env.step(
            action, opp_act)
        self.obs_a, self.obs_b = next_a, next_b
        return r_a, done, next_a


class GymServer:
    def __init__(self, host="127.0.0.1", port=43594, policy=None,
                 seed_base=1000):
        self.host = host
        self.port = port
        self.policy = policy
        self.seed_base = seed_base
        self.sessions_served = 0
        self.sock = None
        self.running = False

    def start(self):
        if self.policy is not None:
            ok, reason = self.policy.check_listener(self.host, self.port)
            if not ok:
                raise PermissionError(f"MIND net policy denied: {reason}")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(16)
        self.running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return self.port

    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass

    def _accept_loop(self):
        while self.running:
            try:
                conn, addr = self.sock.accept()
            except OSError:
                break
            self.sessions_served += 1
            threading.Thread(
                target=self._serve,
                args=(conn, self.seed_base + self.sessions_served),
                daemon=True).start()

    def _serve(self, conn, seed):
        session = _Session(seed)
        f = conn.makefile("rb")
        try:
            while self.running:
                line = f.readline()
                if not line:
                    break
                parts = line.decode().strip().split(",")
                cmd = parts[0].upper()
                if cmd == "RESET":
                    obs, _mask = session.reset()
                    _, mask = session.legal_mask_pair()
                    conn.sendall(_format(obs, mask, 0.0, False).encode())
                elif cmd == "STEP":
                    action = int(parts[1]) if len(parts) > 1 else 0
                    reward, done, obs = session.step(action)
                    _, mask = session.legal_mask_pair()
                    conn.sendall(_format(obs, mask, reward, done).encode())
                elif cmd == "CLOSE":
                    break
        except (OSError, ValueError, IndexError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass
