package com.soultechno.hyperion181.cache;

import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;

/**
 * OpenRS2-standard .dat2/.idx FileStore reader (revision 181 caches).
 *
 * Index entry (6 bytes): 3-byte size, 3-byte first sector.
 * Sector (512 bytes): 2-byte next sector, 2-byte type, 2-byte archive id,
 * 512-byte payload chunk.
 *
 * SPDX-License-Identifier: MIT
 */
public final class FileStore {

    private static final int SECTOR_SIZE = 520;
    private static final int CHUNK_SIZE = 512;

    private final RandomAccessFile data;
    private final RandomAccessFile[] indexes;

    public FileStore(String cacheDir) throws IOException {
        this.data = new RandomAccessFile(cacheDir + "/main_file_cache.dat2", "r");
        this.indexes = new RandomAccessFile[256];
        for (int i = 0; i < indexes.length; i++) {
            var f = new java.io.File(cacheDir + "/main_file_cache.idx" + i);
            if (f.exists()) {
                indexes[i] = new RandomAccessFile(f, "r");
            }
        }
    }

    public int indexCount() {
        int count = 0;
        for (var idx : indexes) {
            if (idx != null) count++;
        }
        return count;
    }

    /** Reads archive {@code file} from reference table {@code index}. */
    public byte[] read(int indexId, int fileId) throws IOException {
        var idx = indexes[indexId];
        if (idx == null) throw new IOException("no index " + indexId);
        long ptr = (long) fileId * 6;
        if (idx.length() < ptr + 6) return null;
        idx.seek(ptr);
        ByteBuffer header = ByteBuffer.allocate(6);
        idx.readFully(header.array());
        int size = ((header.get(0) & 0xFF) << 16) | ((header.get(1) & 0xFF) << 8)
                | (header.get(2) & 0xFF);
        int sector = ((header.get(3) & 0xFF) << 16) | ((header.get(4) & 0xFF) << 8)
                | (header.get(5) & 0xFF);

        ByteBuffer out = ByteBuffer.allocate(size);
        int remaining = size;
        int currentSector = sector;
        while (remaining > 0) {
            data.seek((long) currentSector * SECTOR_SIZE);
            byte[] block = new byte[SECTOR_SIZE];
            data.readFully(block);
            ByteBuffer wrapped = ByteBuffer.wrap(block);
            int nextSector = wrapped.getShort() & 0xFFFF;
            int type = wrapped.get() & 0xFF;
            int archive = wrapped.getShort() & 0xFFFF;
            if (type != indexId || archive != fileId) {
                throw new IOException("sector chain mismatch at " + currentSector);
            }
            int chunk = Math.min(remaining, CHUNK_SIZE);
            byte[] chunkData = new byte[chunk];
            wrapped.get(chunkData);
            out.put(chunkData);
            remaining -= chunk;
            currentSector = nextSector;
        }
        return out.array();
    }
}
