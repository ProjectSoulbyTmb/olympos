package com.soultechno.hyperion181.game;

import java.util.ArrayList;
import java.util.List;

/**
 * World registry: fixed-size player slots (classic 2048) and the 600 ms
 * tick entry point. Single-writer: only the game engine thread mutates
 * world state; network threads hand off via the executor.
 *
 * SPDX-License-Identifier: MIT
 */
public final class World {

    public static final int MAX_PLAYERS = 2048;

    private final Player[] players = new Player[MAX_PLAYERS];
    private final List<Player> active = new ArrayList<>();
    private int freeSlot = 1; // slot 0 reserved

    public synchronized Player register(String name) {
        while (freeSlot < MAX_PLAYERS && players[freeSlot] != null) {
            freeSlot++;
        }
        if (freeSlot >= MAX_PLAYERS) {
            return null;
        }
        Player player = new Player(freeSlot, name);
        players[freeSlot] = player;
        active.add(player);
        return player;
    }

    public synchronized void unregister(Player player) {
        players[player.getId()] = null;
        active.remove(player);
    }

    /** Players within one local view window, capped at 255. */
    public List<Player> localsInView(Player self) {
        List<Player> view = new ArrayList<>(Player.MAX_LOCAL_PLAYERS);
        for (Player p : active) {
            if (p == self) continue;
            if (Math.abs(p.getAbsX() - self.getAbsX()) <= 15
                    && Math.abs(p.getAbsY() - self.getAbsY()) <= 15
                    && p.getHeight() == self.getHeight()
                    && view.size() < Player.MAX_LOCAL_PLAYERS) {
                view.add(p);
            }
        }
        return view;
    }

    public List<Player> getActive() {
        return new ArrayList<>(active);
    }

    /** One 600 ms engine cycle. */
    public void tick() {
        for (Player p : getActive()) {
            p.processMovement();
        }
        // Update building happens per-session in Netty write tasks.
    }
}
