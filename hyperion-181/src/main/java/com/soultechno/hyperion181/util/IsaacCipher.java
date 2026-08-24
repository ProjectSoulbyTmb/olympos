package com.soultechno.hyperion181.util;

/**
 * Bob Jenkins' ISAAC PRNG - literal translation of the public-domain
 * reference rand.c (burtleburtle.net/bob/rand/isaac.html), including his
 * randvect.txt known-answer coverage (zero seed, randinit(TRUE)).
 *
 * Used as the RS2 packet opcode cipher pair seeded by the four login
 * session keys. Client and server hold mirrored instances consuming the
 * same sequence, recovering opcodes deterministically.
 *
 * SPDX-License-Identifier: MIT
 */
public final class IsaacCipher {

    /** Reference constant RANDSIZL. */
    private static final int RANDSIZL = 8;
    /** Reference constant RANDSIZ. */
    private static final int SIZE = 1 << RANDSIZL;
    private static final int MASK = SIZE - 1;

    /** ctx.randmem */
    private final int[] memory = new int[SIZE];
    /** ctx.randrsl - also the seed carrier before randinit */
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

    /**
     * Reference isaac(). The four rngstep macros expand inline; pointer
     * arithmetic becomes explicit indices (m, m2, r).
     */
    public void isaac() {
        int a = aa;
        int b = bb + (++cc);
        int m = 0;
        int m2 = SIZE / 2;
        int r = 0;
        int x;
        int y;

        // First half: m walks the low half while m2 walks the high half.
        while (m < SIZE / 2) {
            x = memory[m];
            a = (a ^ (a << 13)) + memory[m2++];
            y = memory[(x >>> 2) & MASK] + a + b;
            results[r++] = y;
            memory[m++] = memory[(y >>> RANDSIZL) & MASK] + x;

            x = memory[m];
            a = (a ^ (a >>> 6)) + memory[m2++];
            y = memory[(x >>> 2) & MASK] + a + b;
            results[r++] = y;
            memory[m++] = memory[(y >>> RANDSIZL) & MASK] + x;

            x = memory[m];
            a = (a ^ (a << 2)) + memory[m2++];
            y = memory[(x >>> 2) & MASK] + a + b;
            results[r++] = y;
            memory[m++] = memory[(y >>> RANDSIZL) & MASK] + x;

            x = memory[m];
            a = (a ^ (a >>> 16)) + memory[m2++];
            y = memory[(x >>> 2) & MASK] + a + b;
            results[r++] = y;
            memory[m++] = memory[(y >>> RANDSIZL) & MASK] + x;
        }

        // Second half: m2 wraps to the base while m continues upward.
        m2 = 0;
        while (m < SIZE) {
            x = memory[m];
            a = (a ^ (a << 13)) + memory[m2++];
            y = memory[(x >>> 2) & MASK] + a + b;
            results[r++] = y;
            memory[m++] = memory[(y >>> RANDSIZL) & MASK] + x;

            x = memory[m];
            a = (a ^ (a >>> 6)) + memory[m2++];
            y = memory[(x >>> 2) & MASK] + a + b;
            results[r++] = y;
            memory[m++] = memory[(y >>> RANDSIZL) & MASK] + x;

            x = memory[m];
            a = (a ^ (a << 2)) + memory[m2++];
            y = memory[(x >>> 2) & MASK] + a + b;
            results[r++] = y;
            memory[m++] = memory[(y >>> RANDSIZL) & MASK] + x;

            x = memory[m];
            a = (a ^ (a >>> 16)) + memory[m2++];
            y = memory[(x >>> 2) & MASK] + a + b;
            results[r++] = y;
            memory[m++] = memory[(y >>> RANDSIZL) & MASK] + x;
        }

        bb = b;
        aa = a;
    }

    /** Reference mix(a..h) macro over eight accumulators. */
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

    /** Reference randinit(ctx, TRUE): initialize mm[] from randrsl[]. */
    private void randinit(boolean useSeed) {
        aa = bb = cc = 0;
        int[] acc = new int[8];
        for (int i = 0; i < 8; i++) {
            acc[i] = 0x9e3779b9; // the golden ratio
        }
        for (int i = 0; i < 4; i++) {
            mix(acc);
        }
        if (useSeed) {
            for (int i = 0; i < SIZE; i += 8) {
                for (int j = 0; j < 8; j++) {
                    acc[j] += results[i + j];
                }
                mix(acc);
                for (int j = 0; j < 8; j++) {
                    memory[i + j] = acc[j];
                }
            }
            // Second pass so every seed word affects every slot.
            for (int i = 0; i < SIZE; i += 8) {
                for (int j = 0; j < 8; j++) {
                    acc[j] += memory[i + j];
                }
                mix(acc);
                for (int j = 0; j < 8; j++) {
                    memory[i + j] = acc[j];
                }
            }
        } else {
            for (int i = 0; i < SIZE; i += 8) {
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
     * Next value. Consumption order is an implementation choice; mirrored
     * client/server instances stay symmetric regardless.
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
