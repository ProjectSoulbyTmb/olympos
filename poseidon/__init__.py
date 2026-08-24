"""POSEIDON - the tide kernel of the Olympos fleet.

The autonomous commit-and-push workflow: sweeps uncommitted drift,
ships it through the sanctioned lane, settles the mirror.

Import ``poseidon.kernel.TideEngine`` directly (lazy import keeps
package init cheap and avoids cycles).
"""
