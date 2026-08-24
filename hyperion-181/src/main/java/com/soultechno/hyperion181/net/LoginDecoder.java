package com.soultechno.hyperion181.net;

import com.soultechno.hyperion181.util.IsaacCipher;
import com.soultechno.hyperion181.util.Xtea;
import io.netty.buffer.ByteBuf;
import io.netty.channel.ChannelHandlerContext;

import java.math.BigInteger;
import java.security.KeyFactory;
import java.security.PrivateKey;
import java.security.spec.RSAPrivateKeySpec;

/**
 * Stage 2: decodes the RSA login block for revision 181.
 *
 * Wire layout after handshake:
 *   byte   opcode (16 reconnect / 18 fresh)
 *   short  block size
 *   ...    block = RSA_private(block); inside:
 *            byte  1                      (marker)
 *            int[] isaacInSeed[4]         session keys
 *            int[] isaacOutSeed[4]        mirrored pair
 *            long  serverSessionKey
 *            byte  xteaKeyCount (usually 0 here)
 *          then outside-RSA: int revision, byte seedCount,
 *          XTEA-encrypted credentials section containing the password.
 *
 * The decoder emits a {@link LoginRequest} and installs the ISAAC/XTEA
 * codecs, transitioning the pipeline to game-message framing.
 *
 * SPDX-License-Identifier: MIT
 */
public final class LoginDecoder extends io.netty.handler.codec.ByteToMessageDecoder {

    private final PrivateKey rsaKey;

    public LoginDecoder(PrivateKey rsaKey) {
        this.rsaKey = rsaKey;
    }

    @Override
    protected void decode(ChannelHandlerContext ctx, ByteBuf in, List<Object> out)
            throws Exception {
        if (!in.isReadable(3)) {
            return;
        }
        in.readUnsignedByte();               // login type (16/18)
        int blockSize = in.readUnsignedShort();
        if (!in.isReadable(blockSize)) {
            return;
        }
        byte[] block = new byte[blockSize];
        in.readBytes(block);

        BigInteger cipherText = new BigInteger(block);
        BigInteger plain = cipherText.modPow(d(rsaKey), n(rsaKey));
        byte[] decoded = stripLeadingZeros(plain.toByteArray());

        int offset = 1; // marker byte 10 or 1
        int[] inSeed = new int[4];
        int[] outSeed = new int[4];
        for (int i = 0; i < 4; i++) {
            inSeed[i] = readInt(decoded, offset + i * 4);
        }
        for (int i = 0; i < 4; i++) {
            outSeed[i] = readInt(decoded, offset + 16 + i * 4);
        }

        IsaacCipher encodeCipher = new IsaacCipher(outSeed);
        IsaacCipher decodeCipher = new IsaacCipher(inSeed);
        ctx.pipeline().addLast("xtea", new XteaFrameCodec(new Xtea(inSeed)));
        ctx.pipeline().replace(this, "game-decoder",
                new GameMessageDecoder(decodeCipher));
        ctx.pipeline().addBefore("game-decoder", "game-encoder",
                new GameMessageEncoder(encodeCipher));

        out.add(new LoginRequest(new String(decoded, java.nio.charset.StandardCharsets.UTF_8,
                Math.min(decoded.length, 64)).trim(), inSeed));
    }

    private static int readInt(byte[] b, int off) {
        return (b[off] & 0xFF) << 24 | (b[off + 1] & 0xFF) << 16
                | (b[off + 2] & 0xFF) << 8 | (b[off + 3] & 0xFF);
    }

    private static byte[] stripLeadingZeros(byte[] bytes) {
        int start = 0;
        while (start < bytes.length - 1 && bytes[start] == 0) {
            start++;
        }
        byte[] out = new byte[bytes.length - start];
        System.arraycopy(bytes, start, out, 0, out.length);
        return out;
    }

    private static BigInteger d(PrivateKey key) throws Exception {
        return rsaparam(key, "d");
    }

    private static BigInteger n(PrivateKey key) throws Exception {
        return rsaparam(key, "modulus");
    }

    private static BigInteger rsaparam(PrivateKey key, String name) throws Exception {
        KeyFactory factory = KeyFactory.getInstance("RSA");
        var spec = factory.getKeySpec(key, RSAPrivateKeySpec.class);
        return "d".equals(name) ? spec.getPrivateExponent() : spec.getModulus();
    }
}
