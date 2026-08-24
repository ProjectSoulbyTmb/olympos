package com.soultechno.hyperion181.net;

import java.io.ByteArrayOutputStream;

/**
 * Minimal stand-in for the Player appearance writer dependencies used by
 * {@link com.soultechno.hyperion181.game.Player#writeAppearance}, providing
 * the byte-array sink without leaking IO types into the game package.
 *
 * SPDX-License-Identifier: MIT
 */
public final class ByteSink {

    private ByteSink() {
    }

    public static ByteArrayOutputStream stream() {
        return new ByteArrayOutputStream();
    }
}
