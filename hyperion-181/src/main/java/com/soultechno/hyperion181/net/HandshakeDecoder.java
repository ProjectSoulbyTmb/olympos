package com.soultechno.hyperion181.net;

import com.soultechno.hyperion181.util.IsaacCipher;
import io.netty.buffer.ByteBuf;
import io.netty.channel.ChannelHandlerContext;
import io.netty.handler.codec.ByteToMessageDecoder;

import java.util.List;

/**
 * Stage 1: intercepts the RS2 connection handshake. Client sends opcode 14
 * (login) with a name hash; server replies 0 and hands the channel to the
 * {@link LoginDecoder} for the RSA login block.
 *
 * SPDX-License-Identifier: MIT
 */
public final class HandshakeDecoder extends ByteToMessageDecoder {

    public static final int OPCODE_GAME_LOGIN = 14;
    public static final int RESPONSE_EXCHANGE_KEYS = 0;

    @Override
    protected void decode(ChannelHandlerContext ctx, ByteBuf in, List<Object> out) {
        if (!in.isReadable(2)) {
            return;
        }
        int opcode = in.readUnsignedByte();
        if (opcode != OPCODE_GAME_LOGIN) {
            throw new IllegalStateException("bad handshake opcode " + opcode);
        }
        in.readUnsignedByte(); // name hash % 16 routing nibble

        ByteBuf reply = ctx.alloc().buffer(1);
        reply.writeByte(RESPONSE_EXCHANGE_KEYS);
        ctx.writeAndFlush(reply);

        ctx.pipeline().replace(this, "login-decoder", new LoginDecoder());
    }
}
