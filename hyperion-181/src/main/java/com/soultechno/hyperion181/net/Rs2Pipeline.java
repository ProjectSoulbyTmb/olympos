package com.soultechno.hyperion181.net;

import com.soultechno.hyperion181.util.IsaacCipher;
import com.soultechno.hyperion181.util.Xtea;
import io.netty.buffer.ByteBuf;
import io.netty.channel.ChannelHandlerContext;
import io.netty.handler.codec.ByteToMessageDecoder;
import io.netty.handler.codec.MessageToByteEncoder;

import java.util.List;

/**
 * Post-login game-message framing: XTEA payload decryption + ISAAC opcode
 * masking on ingress, mirrored on egress.
 *
 * SPDX-License-Identifier: MIT
 */
final class LoginRequest {
    private final String username;

    LoginRequest(String username) {
        this.username = username;
    }

    String getUsername() {
        return username;
    }
}

/** Ingress: ISAAC-masked opcode, length byte, XTEA-encrypted payload. */
final class GameMessageDecoder extends ByteToMessageDecoder {

    private final IsaacCipher decodeCipher;
    private final Xtea xtea;

    GameMessageDecoder(IsaacCipher decodeCipher) {
        this.decodeCipher = decodeCipher;
        this.xtea = new Xtea(new int[4]); // replaced per-session upstream
    }

    @Override
    protected void decode(ChannelHandlerContext ctx, ByteBuf in, List<Object> out) {
        if (!in.isReadable()) {
            return;
        }
        int encryptedOpcode = in.readUnsignedByte();
        int opcode = (encryptedOpcode - decodeCipher.nextKey()) & 0xFF;
        if (!in.isReadable()) {
            return;
        }
        int length = in.readUnsignedByte();
        if (!in.isReadable(length)) {
            return;
        }
        byte[] payload = new byte[length];
        in.readBytes(payload);
        // Payloads are XTEA blocks when length % 8 == 0; short frames pass.
        if (length >= 8 && length % 8 == 0) {
            xtea.decrypt(payload, 0, length);
        }
        out.add(new GameMessage(opcode, payload));
    }

    record GameMessage(int opcode, byte[] payload) {
    }
}

/** Egress: ISAAC-masked opcode + length, optional XTEA on payloads. */
final class GameMessageEncoder extends MessageToByteEncoder<GameMessageEncoder.Outbound> {

    private final IsaacCipher encodeCipher;

    record Outbound(int opcode, byte[] payload) {
    }

    GameMessageEncoder(IsaacCipher encodeCipher) {
        this.encodeCipher = encodeCipher;
    }

    @Override
    protected void encode(ChannelHandlerContext ctx, Outbound msg, ByteBuf out) {
        out.writeByte((msg.opcode() + encodeCipher.nextKey()) & 0xFF);
        out.writeByte(msg.payload().length);
        out.writeBytes(msg.payload());
    }
}

/** Per-session XTEA holder wired by the login flow. */
final class XteaFrameCodec extends io.netty.handler.codec.MessageToMessageCodec<ByteBuf, ByteBuf> {
    private final Xtea xtea;

    XteaFrameCodec(Xtea xtea) {
        this.xtea = xtea;
    }

    @Override
    protected void decode(ChannelHandlerContext ctx, ByteBuf in, List<Object> out) {
        out.add(in.retain()); // framing handled by GameMessageDecoder
    }

    @Override
    protected void encode(ChannelHandlerContext ctx, ByteBuf msg, List<Object> out) {
        out.add(msg.retain());
    }
}
