package com.soultechno.hyperion181.game;

import com.soultechno.hyperion181.net.PacketBuilder;

import java.util.ArrayList;
import java.util.List;

/**
 * Builds the revision-profile player update message (317 lineage: opcode 81):
 * bit section for movement/init of every viewed player, followed by the
 * byte-aligned mask section carrying appearance blocks.
 *
 * Movement encoding per local player:
 *   1 bit  0 (no teleport flag)
 *   1 bit  requiresMask
 *   1 bit  running? then per step 3 bits direction (+1 offset)
 *
 * Added players emit an 11-bit index, discard-walking flag, 5-bit regional
 * offsets, appearance flag, then their appearance block in the mask section.
 *
 * SPDX-License-Identifier: MIT
 */
public final class PlayerUpdater {

    /** Direction lookup: dx/dy pair -> 3-bit walk value (0 = no movement). */
    private static final int[][] DIRECTION = {
        {0, 0}, {-1, 1}, {0, 1}, {1, 1}, {-1, 0}, {1, 0}, {-1, -1}, {0, -1}, {1, -1},
    };

    public static PacketBuilder buildUpdate(Player self, List<Player> locals,
                                            List<Player> additions) {
        PacketBuilder out = new PacketBuilder();
        out.accessBits();

        // Own movement first.
        if (self.isTeleporting()) {
            out.putBits(1, 1);
            out.putBits(2, self.getHeight());
            out.putBits(13, self.getAbsY() & 0x1FFF);
            out.putBits(13, self.getAbsX() & 0x1FFF);
            self.clearTeleporting();
        } else {
            int ownDir = self.stepDirection();
            if (ownDir > 0) {
                out.putBits(1, 1);
                out.putBits(2, self.isRunning() ? 2 : 1);
                out.putBits(3, ownDir);
                if (self.isRunning()) {
                    int second = self.stepDirection();
                    out.putBits(3, second); // 0 terminates a single-tile run
                }
            } else {
                out.putBits(1, self.isAppearanceUpdateRequired() ? 1 : 0);
            }
        }

        // Existing locals: movement or removal.
        for (Player other : locals) {
            int dir = other.stepDirection();
            if (dir > 0) {
                out.putBits(1, 1);      // moving
                out.putBits(2, other.isRunning() ? 2 : 1);
                out.putBits(3, dir);
                if (other.isRunning()) {
                    out.putBits(3, other.stepDirection());
                }
            } else {
                out.putBits(1, 0);      // remove from the local list
            }
        }

        // Additions: index + regional offsets + appearance-required flag.
        PacketBuilder masks = new PacketBuilder();
        for (Player added : additions) {
            out.putBits(11, added.getId());
            out.putBits(1, added.isAppearanceUpdateRequired() ? 1 : 0);
            out.putBits(1, 1); // discard walking queue client-side
            int dx = added.getAbsX() - self.getAbsX();
            int dy = added.getAbsY() - self.getAbsY();
            out.putBits(5, dy & 0x1F);
            out.putBits(5, dx & 0x1F);
            added.writeAppearance(masks);
        }
        out.accessBytes();
        return out;
    }
}
