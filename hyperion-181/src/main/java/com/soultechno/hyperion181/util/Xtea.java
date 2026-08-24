package com.soultechno.hyperion181.util;

/**
 * XTEA block cipher (32 rounds) as used by OSRS revision 181 game-message
 * payloads. Keys arrive inside the RSA login block; four ints per session.
 *
 * SPDX-License-Identifier: MIT
 */
public final class Xtea {

    private static final int DELTA = 0x9E3779B9;
    private static final int ROUNDS = 32;
    /** delta * 32 mod 2^32 - decipher termination constant. */
    private static final int SUM_INIT_DECIPHER = 0xC6EF3720;

    private final int[] key;

    public Xtea(int[] key) {
        if (key.length < 4) throw new IllegalArgumentException("xtea needs 4 words");
        this.key = key.clone();
    }

    /** Decrypts {@code data} in place, XTEA blocks of 8 bytes from offset. */
    public void decrypt(byte[] data, int offset, int length) {
        for (int pos = offset; pos + 8 <= offset + length; pos += 8) {
            int v0 = (data[pos] << 24) | (data[pos + 1] & 0xFF) << 16
                    | (data[pos + 2] & 0xFF) << 8 | (data[pos + 3] & 0xFF);
            int v1 = (data[pos + 4] << 24) | (data[pos + 5] & 0xFF) << 16
                    | (data[pos + 6] & 0xFF) << 8 | (data[pos + 7] & 0xFF);
            int sum = SUM_INIT_DECIPHER;
            for (int i = 0; i < ROUNDS; i++) {
                v1 -= (((v0 << 4) ^ (v0 >>> 5)) + v0) ^ (sum + key[(sum >>> 11) & 3]);
                sum -= DELTA;
                v0 -= (((v1 << 4) ^ (v1 >>> 5)) + v1) ^ (sum + key[sum & 3]);
            }
            data[pos] = (byte) (v0 >> 24);
            data[pos + 1] = (byte) (v0 >> 16);
            data[pos + 2] = (byte) (v0 >> 8);
            data[pos + 3] = (byte) v0;
            data[pos + 4] = (byte) (v1 >> 24);
            data[pos + 5] = (byte) (v1 >> 16);
            data[pos + 6] = (byte) (v1 >> 8);
            data[pos + 7] = (byte) v1;
        }
    }

    /** Encrypts {@code data} in place, XTEA blocks of 8 bytes from offset. */
    public void encrypt(byte[] data, int offset, int length) {
        for (int pos = offset; pos + 8 <= offset + length; pos += 8) {
            int v0 = (data[pos] << 24) | (data[pos + 1] & 0xFF) << 16
                    | (data[pos + 2] & 0xFF) << 8 | (data[pos + 3] & 0xFF);
            int v1 = (data[pos + 4] << 24) | (data[pos + 5] & 0xFF) << 16
                    | (data[pos + 6] & 0xFF) << 8 | (data[pos + 7] & 0xFF);
            int sum = 0;
            for (int i = 0; i < ROUNDS; i++) {
                v0 += (((v1 << 4) ^ (v1 >>> 5)) + v1) ^ (sum + key[sum & 3]);
                sum += DELTA;
                v1 += (((v0 << 4) ^ (v0 >>> 5)) + v0) ^ (sum + key[(sum >>> 11) & 3]);
            }
            data[pos] = (byte) (v0 >> 24);
            data[pos + 1] = (byte) (v0 >> 16);
            data[pos + 2] = (byte) (v0 >> 8);
            data[pos + 3] = (byte) v0;
            data[pos + 4] = (byte) (v1 >> 24);
            data[pos + 5] = (byte) (v1 >> 16);
            data[pos + 6] = (byte) (v1 >> 8);
            data[pos + 7] = (byte) v1;
        }
    }
}
