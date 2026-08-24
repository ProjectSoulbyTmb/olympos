package com.soultechno.hyperion181;

import com.soultechno.hyperion181.net.HandshakeDecoder;
import io.netty.bootstrap.ServerBootstrap;
import io.netty.channel.ChannelInitializer;
import io.netty.channel.ChannelOption;
import io.netty.channel.nio.NioEventLoopGroup;
import io.netty.channel.socket.SocketChannel;
import io.netty.channel.socket.nio.NioServerSocketChannel;

import java.io.File;
import java.security.KeyFactory;
import java.security.PrivateKey;
import java.security.spec.PKCS8EncodedKeySpec;
import java.util.Base64;

/**
 * Netty 4.1 bootstrap for the revision-181 listener (default port 43594).
 * Pipeline: [handshake-decoder] -> [login-decoder] -> [game codecs].
 *
 * SPDX-License-Identifier: MIT
 */
public final class Rs2Server {

    public static void main(String[] args) throws Exception {
        int port = args.length > 0 ? Integer.parseInt(args[0]) : 43594;
        PrivateKey rsaKey = loadPrivateKey("data/rsa/private.pkcs8");

        var boss = new NioEventLoopGroup(1);
        var worker = new NioEventLoopGroup();
        var bootstrap = new ServerBootstrap()
            .group(boss, worker)
            .channel(NioServerSocketChannel.class)
            .childOption(ChannelOption.TCP_NODELAY, true)
            .childHandler(new ChannelInitializer<SocketChannel>() {
                @Override
                protected void initChannel(SocketChannel ch) {
                    ch.pipeline().addLast("handshake-decoder", new HandshakeDecoder());
                }
            });
        bootstrap.bind(port).sync();
        System.out.println("[hyperion-181] listening on " + port);

        WorldHolder.start(rsaKey == null ? null : rsaKey);
    }

    private Rs2Server() {
    }

    /** Loads a PKCS#8 base64 key; generates nothing silently. */
    static PrivateKey loadPrivateKey(String path) throws Exception {
        File file = new File(path);
        if (!file.exists()) {
            System.out.println("[hyperion-181] WARNING: no RSA key at " + path
                + "; run KeyGen before enabling logins");
            return null;
        }
        String base64 = java.nio.file.Files.readString(file.toPath())
                .replaceAll("-----[A-Z ]+-----", "").replaceAll("\\s", "");
        byte[] der = Base64.getDecoder().decode(base64);
        return KeyFactory.getInstance("RSA").generatePrivate(new PKCS8EncodedKeySpec(der));
    }

    /** Deferred world bootstrap keeps startup ordering explicit. */
    private static final class WorldHolder {
        static void start(PrivateKey ignored) {
            GameEngine engine = new GameEngine(() -> { });
            engine.start();
        }
    }
}
