package com.soultechno.hyperion181;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * The 600 ms single-threaded game loop (Hyperion doctrine: one engine
 * thread owns all mutable world state; networking only submits work).
 * Overruns are logged so tick discipline is observable.
 *
 * SPDX-License-Identifier: MIT
 */
public final class GameEngine {

    public static final int TICK_MS = 600;

    private final ScheduledExecutorService executor =
            Executors.newSingleThreadScheduledExecutor(r -> {
                Thread t = new Thread(r, "game-engine");
                t.setDaemon(true);
                return t;
            });
    private final Runnable cycle;
    private long lastStart;

    public GameEngine(Runnable cycle) {
        this.cycle = cycle;
    }

    public void start() {
        lastStart = System.nanoTime();
        executor.scheduleAtFixedRate(this::runCycle, TICK_MS, TICK_MS,
                TimeUnit.MILLISECONDS);
    }

    private void runCycle() {
        long now = System.nanoTime();
        long overrunMs = (now - lastStart) / 1_000_000 - TICK_MS;
        if (overrunMs > 0) {
            System.out.printf("[engine] tick overran budget by %d ms%n", overrunMs);
        }
        try {
            cycle.run();
        } catch (Throwable t) {
            System.out.printf("[engine] cycle error: %s%n", t);
        }
        lastStart = System.nanoTime();
    }
}
