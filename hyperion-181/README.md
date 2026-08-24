# hyperion-181

Hyperion-doctrine OSRS revision-#181 server base: Java 11, Gradle,
Netty 4.1, ISAAC/XTEA/RSA login pipeline, 600 ms single-thread engine,
bit-level player updating, OpenRS2-standard cache reader.

## Verified vs pending

| Component | Status |
|---|---|
| ISAAC cipher | **Verified against Jenkins' randvect.txt golden vectors** (512/512 values) |
| XTEA codec | Round-trip unit test |
| PacketBuilder bit alignment | Unit tests (MSB-first packing, padding) |
| Handshake/login decode | Implemented; RSA keys must be generated (see below) |
| Player updating (movement + appearance) | Implemented against 317-lineage spec; rev-181 deltas isolated in constants |
| Cache FileStore | dat2/idx sector-chain reader per OpenRS2 layout |

## Environment bootstrap (Windows)

```powershell
winget install EclipseAdoptium.Temurin.11.JDK
winget install Gradle.Gradle
java -version   # 11.0.x
```

## Build and run

```powershell
cd hyperion-181
gradle wrapper --gradle-version 8.7   # one-time; generates gradlew
.\gradlew test                        # protocol payload verification
.\gradlew run                         # listens on 43594
```

## RSA session keys

Logins require an RSA keypair at `data/rsa/private.pkcs8` (PKCS#8, base64).
Generate once:

```powershell
keytool -genkeypair -algorithm RSA -keysize 2048 \
  -alias rs181 -keystore data\rsa\store.jks -storepass changeit
```

(Or export PKCS#8 from any tool.) The client's public modulus/exponent must
match — for local sandbox use only.

## Revision profile note

Packet opcodes and mask ordering shift between revisions. All such constants
are isolated in the updater/net classes; when mapping deltas from the #181
client, change constants only — never the bit-packing core.
