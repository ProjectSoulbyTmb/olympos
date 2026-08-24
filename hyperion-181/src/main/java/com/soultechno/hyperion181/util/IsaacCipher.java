package com.soultechno.hyperion181.util;

/**
 * Bob Jenkins' ISAAC PRNG - literal translation of the public-domain
 * readable.c reference (burtleburtle.net/bob/c/readable.c), verified
 * against his published randvect.txt known-answer vectors.
 *
 * Used as the RS2 packet opcode cipher pair seeded by the four login
 * session keys. Client and server hold mirrored instances consuming the
 * same sequence, recovering opcodes deterministically.
 *
 * SPDX-License-Identifier: MIT
 */
public final class IsaacCipher {

    private static final int SIZE = 256;
    private static final int MASK = SIZE - 1;

    /** ctx.mm */
    private final int[] memory = new int[SIZE];
    /** ctx.randrsl - seed carrier before init, results afterwards */
    private final int[] results = new int[SIZE];

    private int aa;
    private int bb;
    private int cc;
    private int remaining = SIZE;

    public IsaacCipher() {
        this(new int[SIZE]);
    }

    public IsaacCipher(int[] seed) {
        System.arraycopy(seed, 0, results, 0, Math.min(seed.length, SIZE));
        randinit(true);
    }

    /** readable.c isaac(): one full 256-value block. */
    public void isaac() {
        cc += 1;
        bb += cc;
        for (int i = 0; i < SIZE; i++) {
            int x = memory[i];
            int k = i & 3;
            if (k == 0) {
                aa ^= aa << 13;
            } else if (k == 1) {
                aa ^= aa >>> 6;
            } else if (k == 2) {
                aa ^= aa << 2;
            } else {
                aa ^= aa >>> 16;
            }
            aa += memory[(i + 128) % SIZE];
            // mm[i] <- intermediate; randrsl[i] <- new bb chained on old x.
            int y = memory[(x >>> 2) & MASK] + aa + bb;
            memory[i] = y;
            results[i] = bb = memory[(y >>> 10) & MASK] + x;
        }
    }

    /** readable.c mix(a..h) macro. */
    private static void mix(int[] v) {
        int a = v[0], b = v[1], c = v[2], d = v[3];
        int e = v[4], f = v[5], g = v[6], h = v[7];
        a ^= b << 11;  d += a; b += c;
        b ^= c >>> 2;  e += b; c += d;
        c ^= d << 8;   f += c; d += e;
        d ^= e >>> 16; g += d; e += f;
        e ^= f << 10;  h += e; f += g;
        f ^= g >>> 4;  a += f; g += h;
        g ^= h << 8;   b += g; h += a;
        h ^= a >>> 9;  c += h; a += b;
        v[0] = a; v[1] = b; v[2] = c; v[3] = d;
        v[4] = e; v[5] = f; v[6] = g; v[7] = h;
    }

    /** readable.c randinit(flag): scramble golden state, fold seed twice. */
    private void randinit(boolean useSeed) {
        aa = bb = cc = 0;
        int[] acc = new int[8];
        for (int i = 0; i < 8; i++) {
            acc[i] = 0x9e3779b9; // the golden ratio
        }
        for (int i = 0; i < 4; i++) {
            mix(acc);
        }
        for (int i = 0; i < SIZE; i += 8) {
            if (useSeed) {
                for (int j = 0; j < 8; j++) {
                    acc[j] += results[i + j];
                }
            }
            mix(acc);
            for (int j = 0; j < 8; j++) {
                memory[i + j] = acc[j];
            }
        }
        if (useSeed) {
            // Second pass so every seed word affects every memory slot.
            for (int i = 0; i < SIZE; i += 8) {
                for (int j = 0; j < 8; j++) {
                    acc[j] += memory[i + j];
                }
                mix(acc);
                for (int j = 0; j < 8; j++) {
                    memory[i + j] = acc[j];
                }
            }
        }
        isaac();
        remaining = SIZE;
    }

    /**
     * Next value. readable.c consumes descending via randcnt-- to zero;
     * mirrored client/server instances stay symmetric under any fixed
     * consumption policy.
     */
    public int next() {
        if (remaining == 0) {
            isaac();
            remaining = SIZE;
        }
        return results[--remaining];
    }

    /** Masked byte key used to obfuscate packet opcodes. */
    public int nextKey() {
        return next() & 0xFF;
    }

    /** Copy of the current result window (test/golden-vector access). */
    public int[] snapshotResults() {
        return results.clone();
    }
}
