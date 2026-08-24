package com.soultechno.hyperion181.net;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/**
 * Big-endian RS2 packet writer supporting the Player Updating Protocol's
 * bit-level sections. Bits are written MSB-first; {@link #accessBytes()}
 * realigns to the next whole-byte edge before byte writes resume.
 *
 * SPDX-License-Identifier: MIT
 */
public final class PacketBuilder {

    private static final int GROW = 512;

    private byte[] buffer = new byte[GROW];
    /** Committed byte length (byte mode). */
    private int written;
    /** Current write cursor in BITS; negative while in byte mode. */
    private int bitCursor = -1;

    private void ensure(int capacity) {
        if (capacity > buffer.length) {
            buffer = Arrays.copyOf(buffer, Math.max(buffer.length * 2, capacity));
        }
    }

    public PacketBuilder putByte(int value) {
        if (bitCursor >= 0) {
            throw new IllegalStateException("finish bit section first");
        }
        ensure(written + 1);
        buffer[written++] = (byte) value;
        return this;
    }

    public PacketBuilder putShort(int value) {
        return putByte(value >> 8).putByte(value);
    }

    public PacketBuilder putInt(int value) {
        return putShort(value >> 16).putShort(value);
    }

    public PacketBuilder putLong(long value) {
        for (int shift = 56; shift >= 0; shift -= 8) {
            putByte((int) (value >> shift));
        }
        return this;
    }

    public PacketBuilder putString(String text) {
        for (byte b : text.getBytes(StandardCharsets.UTF_8)) {
            putByte(b & 0xFF);
        }
        return putByte(10); // RS2 string terminator
    }

    public PacketBuilder putBytes(byte[] bytes) {
        ensure(written + bytes.length);
        System.arraycopy(bytes, 0, buffer, written, bytes.length);
        written += bytes.length;
        return this;
    }

    /** Commits any open bit section, realigning to a whole byte. */
    private void alignToByte() {
        if (bitCursor >= 0) {
            written = (bitCursor + 7) >> 3;
            bitCursor = -1;
        }
    }

    /** Enters bit mode at the next whole-byte boundary. */
    public PacketBuilder accessBits() {
        alignToByte();
        bitCursor = written * 8;
        return this;
    }

    /** Writes {@code bits} of {@code value}, MSB-first. */
    public PacketBuilder putBits(int bits, int value) {
        if (bitCursor < 0) {
            throw new IllegalStateException("call accessBits() first");
        }
        for (int i = bits - 1; i >= 0; i--) {
            int bit = (value >>> i) & 1;
            int byteIndex = bitCursor >> 3;
            ensure(byteIndex + 1);
            if ((bitCursor & 7) == 0) {
                buffer[byteIndex] = 0; // fresh byte in the bit stream
            }
            buffer[byteIndex] |= (byte) (bit << (7 - (bitCursor & 7)));
            bitCursor++;
        }
        return this;
    }

    /** Leaves bit mode; the bit stream is padded to a whole byte. */
    public PacketBuilder accessBytes() {
        if (bitCursor >= 0) {
            written = (bitCursor + 7) >> 3;
            bitCursor = -1;
        }
        return this;
    }

    public int length() {
        return bitCursor >= 0 ? ((bitCursor + 7) >> 3) : written;
    }

    public byte[] toArray() {
        int size = length();
        return Arrays.copyOfRange(buffer, 0, size);
    }
}
