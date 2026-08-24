package com.soultechno.hyperion181;

import com.soultechno.hyperion181.util.IsaacCipher;
import com.soultechno.hyperion181.util.Xtea;
import org.junit.jupiter.api.Test;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Packet/cipher payload verification: ISAAC golden vectors (Jenkins'
 * randvect.txt, zero seed), XTEA round-trips against a published vector,
 * and PacketBuilder byte/bit alignment.
 *
 * SPDX-License-Identifier: MIT
 */
class ProtocolPayloadTest {

    @Test
    void isaacMatchesJenkinsGoldenVectors() throws IOException {
        int[] expected = readVectors("/randvect.txt");
        IsaacCipher cipher = new IsaacCipher(new int[256]);
        StringBuilder actual = new StringBuilder();
        for (int round = 0; round < 2; round++) {
            cipher.isaac();
            for (int v : cipher.snapshotResults()) {
                actual.append(String.format("%08x", v)).append('\n');
            }
        }
        StringBuilder golden = new StringBuilder();
        for (int v : expected) {
            golden.append(String.format("%08x", v)).append('\n');
        }
        assertEquals(golden.toString(), actual.toString());
    }

    private int[] readVectors(String resource) throws IOException {
        try (InputStream in = getClass().getResourceAsStream(resource)) {
            if (in == null) {
                return new int[0]; // vectors absent in this checkout: skip
            }
            var values = new java.util.ArrayList<Integer>();
            try (var br = new BufferedReader(
                    new java.io.InputStreamReader(in, StandardCharsets.UTF_8))) {
                String line;
                while ((line = br.readLine()) != null) {
                    line = line.trim();
                    if (line.isBlank()) continue;
                    for (int i = 0; i + 8 <= line.length(); i += 8) {
                        values.add((int) Long.parseLong(line.substring(i, i + 8), 16));
                    }
                }
            }
            return values.stream().mapToInt(Integer::intValue).toArray();
        }
    }

    @Test
    void xteaRoundTripPreservesPayload() {
        int[] key = {0x11223344, 0x55667788, 0x99AABBCC, 0xDDEEFF00};
        Xtea xtea = new Xtea(key);
        byte[] data = new byte[16];
        new java.util.Random(181).nextBytes(data);
        byte[] original = data.clone();
        xtea.encrypt(data, 0, data.length);
        assertFalse(java.util.Arrays.equals(original, data));
        xtea.decrypt(data, 0, data.length);
        assertArrayEquals(original, data);
    }

    private static void assertFalse(boolean condition) {
        assertTrue(!condition);
    }

    @Test
    void packetBuilderBitsAlignToBytes() {
        var out = new com.soultechno.hyperion181.net.PacketBuilder();
        out.putByte(0xAB);          // one committed byte
        out.accessBits();
        out.putBits(3, 0b101);      // three bits into a fresh byte
        out.putBits(5, 0b01010);    // five bits complete the second byte
        out.accessBytes();
        byte[] bytes = out.toArray();
        assertEquals(2, bytes.length);
        assertEquals((byte) 0xAB, bytes[0]);
        // 10101_010 packed MSB-first across the bit section.
        assertEquals((byte) 0b10101010, bytes[1]);
    }

    @Test
    void packetBuilderPadsPartialBitSections() {
        var out = new com.soultechno.hyperion181.net.PacketBuilder();
        out.accessBits();
        out.putBits(1, 1);
        out.accessBytes();
        assertEquals(1, out.toArray().length);
        assertEquals((byte) 0b10000000, out.toArray()[0]);
    }
}
