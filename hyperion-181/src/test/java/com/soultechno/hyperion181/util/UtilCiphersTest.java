package com.soultechno.hyperion181.util;

import org.junit.jupiter.api.Test;

import java.util.Random;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * M0 gate: both ciphers must be deterministic and self-inverse so the
 * login handshake is reproducible in tests without a live client.
 */
class UtilCiphersTest {

    @Test
    void isaacIsDeterministicForSameSeed() {
        int[] seed = new int[256];
        Random r = new Random(1337);
        for (int i = 0; i < seed.length; i++) seed[i] = r.nextInt();

        IsaacCipher a = new IsaacCipher(seed);
        IsaacCipher b = new IsaacCipher(seed);
        for (int i = 0; i < 1024; i++) {
            assertEquals(a.next(), b.next(), "divergence at " + i);
        }
    }

    @Test
    void isaacZeroSeedProducesKnownFirstBlockShape() {
        // readable.c with an all-zero seed must still emit a full,
        // non-trivial block: no repeated adjacent words, not all zero.
        IsaacCipher z = new IsaacCipher(new int[256]);
        int repeats = 0;
        int prev = z.next();
        for (int i = 1; i < 64; i++) {
            int v = z.next();
            if (v == prev) repeats++;
            prev = v;
        }
        org.junit.jupiter.api.Assertions.assertTrue(repeats < 4,
                "zero-seed output looks degenerate");
    }

    @Test
    void xteaRoundTrips() {
        int[] key = {0x11223344, 0x55667788, 0x99aabbcc, 0xddeeff01};
        Xtea x = new Xtea(key);
        byte[] buf = new byte[16];
        new Random(7).nextBytes(buf);
        byte[] plain = buf.clone();
        x.encrypt(buf, 0, buf.length);
        org.junit.jupiter.api.Assertions.assertFalse(
                java.util.Arrays.equals(plain, buf), "encrypt was a no-op");
        x.decrypt(buf, 0, buf.length);
        org.junit.jupiter.api.Assertions.assertArrayEquals(
                plain, buf, "decrypt did not restore plaintext");
    }

    @Test
    void xteaIgnoresTrailingPartialBlock() {
        int[] key = {1, 2, 3, 4};
        Xtea x = new Xtea(key);
        byte[] buf = new byte[10];          // 8-byte block + 2 trailing
        new Random(9).nextBytes(buf);
        byte[] plain = buf.clone();
        x.encrypt(buf, 0, buf.length);
        org.junit.jupiter.api.Assertions.assertFalse(
                java.util.Arrays.equals(java.util.Arrays.copyOfRange(plain, 0, 8),
                        java.util.Arrays.copyOfRange(buf, 0, 8)),
                "first block was not encrypted");
        org.junit.jupiter.api.Assertions.assertArrayEquals(
                java.util.Arrays.copyOfRange(plain, 8, 10),
                java.util.Arrays.copyOfRange(buf, 8, 10),
                "trailing bytes must be untouched");
        x.decrypt(buf, 0, buf.length);
        org.junit.jupiter.api.Assertions.assertArrayEquals(
                plain, buf, "roundtrip failed");
    }

    private static void assertArrayEquals(byte[] want, int off, int len,
                                          byte[] got) {
        org.junit.jupiter.api.Assertions.assertArrayEquals(
                java.util.Arrays.copyOfRange(want, off, off + len),
                java.util.Arrays.copyOfRange(got, off, off + len));
    }
}
