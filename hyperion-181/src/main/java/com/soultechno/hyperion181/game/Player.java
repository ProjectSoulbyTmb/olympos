package com.soultechno.hyperion181.game;

import com.soultechno.hyperion181.net.PacketBuilder;

/**
 * Player entity: identity, absolute coordinates, movement queue, appearance,
 * and the per-player local view list capped at 255 entries (8-bit indices).
 *
 * SPDX-License-Identifier: MIT
 */
public final class Player {

    /** OSRS player updating supports 8-bit local indices. */
    public static final int MAX_LOCAL_PLAYERS = 255;

    private final int id;
    private final String name;
    private final long encodedName;
    private int absX = 3222;
    private int absY = 3222;
    private int height;
    private boolean teleporting;
    private boolean appearanceUpdateRequired = true;
    private final int[] equipment = new int[12];
    private int combatLevel = 3;
    private final java.util.ArrayDeque<int[]> waypoints = new java.util.ArrayDeque<>();
    private boolean running;

    public Player(int id, String name) {
        this.id = id;
        this.name = name;
        this.encodedName = encodeName(name);
    }

    /** RS2 base-37 name encoding. */
    public static long encodeName(String name) {
        long l = 0L;
        for (int i = 0; i < name.length() && i < 12; i++) {
            char c = name.charAt(i);
            l *= 37L;
            if (c >= 'A' && c <= 'Z') l += c + 1 - 'A';
            else if (c >= 'a' && c <= 'z') l += c + 1 - 'a';
            else if (c >= '0' && c <= '9') l += 27 + c - '0';
        }
        while (l % 37L == 0L && l != 0L) l /= 37L;
        return l;
    }

    public void queueStep(int dx, int dy) {
        int[] last = waypoints.isEmpty() ? new int[]{absX, absY} : waypoints.getLast();
        waypoints.add(new int[]{last[0] + dx, last[1] + dy});
    }

    public void finishTeleport(int x, int y, int height) {
        waypoints.clear();
        this.absX = x;
        this.absY = y;
        this.height = height;
        this.teleporting = true;
    }

    /** Advances one tile along the queued path (called once per tick). */
    public void processMovement() {
        if (teleporting) {
            return; // consumed by the updater this tick
        }
        int[] next = waypoints.pollFirst();
        if (next != null) {
            absX = next[0];
            absY = next[1];
        }
    }

    public void setEquipment(int slot, int itemId) {
        if (slot >= 0 && slot < equipment.length) {
            equipment[slot] = itemId;
            appearanceUpdateRequired = true;
        }
    }

    public int getId() { return id; }
    public String getName() { return name; }
    public long getEncodedName() { return encodedName; }
    public int getAbsX() { return absX; }
    public int getAbsY() { return absY; }
    public int getHeight() { return height; }
    public boolean isRunning() { return running; }
    public void setRunning(boolean running) { this.running = running; }
    public boolean isTeleporting() { return teleporting; }
    public void clearTeleporting() { teleporting = false; }
    public boolean isAppearanceUpdateRequired() { return appearanceUpdateRequired; }
    public void resetAppearanceUpdateRequired() { appearanceUpdateRequired = false; }
    public int[] getEquipment() { return equipment.clone(); }
    public int getCombatLevel() { return combatLevel; }
    public java.util.ArrayDeque<int[]> getWaypoints() { return waypoints; }

    /** Direction table: index -> {dx, dy}; 0 is reserved for "no step". */
    public static final int[][] DIRECTION = {
        {0, 0}, {-1, 1}, {0, 1}, {1, 1}, {-1, 0}, {1, 0}, {-1, -1}, {0, -1}, {1, -1},
    };

    /** Pops one waypoint and returns its 3-bit direction (0 = none left). */
    public int stepDirection() {
        if (teleporting || waypoints.isEmpty()) {
            return 0;
        }
        int[] target = waypoints.pollFirst();
        int dx = Integer.signum(target[0] - absX);
        int dy = Integer.signum(target[1] - absY);
        absX += dx;
        absY += dy;
        for (int i = 1; i < DIRECTION.length; i++) {
            if (DIRECTION[i][0] == dx && DIRECTION[i][1] == dy) {
                return i;
            }
        }
        return 0;
    }

    /** Writes the classic appearance block into {@code out}. */
    public void writeAppearance(PacketBuilder out) {
        var enc = new java.io.ByteArrayOutputStream();
        enc.write(0); // transform byte: 0 = no transmutation
        // name
        long n = encodedName;
        for (int shift = 56; shift >= 0; shift -= 8) {
            enc.write((int) (n >> shift));
        }
        enc.write(combatLevel);
        for (int i = 0; i < 12; i++) {
            short item = (short) equipment[i];
            enc.write(item >> 8);
            enc.write(item);
        }
        // five clothing colour words (defaults)
        for (int color : new int[]{0x191E, 0x2D38, 0x353B, 0x3F47, 0x494F}) {
            enc.write(color >> 8);
            enc.write(color);
        }
        // animation indices: stand/turn90/turn180/turn270/walk/run... (defaults)
        short[] anims = {0x333, 0x334, 0x335, 0x336, 0x337, 0x338, 0x339};
        for (short a : anims) {
            enc.write(a >> 8);
            enc.write(a);
        }
        byte[] body = enc.toByteArray();
        out.putShort(body.length); // "A"-type smart length
        out.putBytes(body);
    }
}
