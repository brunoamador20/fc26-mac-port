/* SHA-256 (FIPS 180-4) without a platform library: the ro service hashes an NRO as Horizon's does, on any host
   (the Linux tests run the same code as the Mac runtime). */
#pragma once
#include <stddef.h>
#include <stdint.h>

typedef struct { uint32_t h[8]; uint64_t bytes; uint8_t block[64]; size_t used; } RoSha256;
void ro_sha256_init(RoSha256 *c);
void ro_sha256_update(RoSha256 *c, const void *data, size_t size);
void ro_sha256_final(RoSha256 *c, uint8_t out[32]);
void ro_sha256(const void *data, size_t size, uint8_t out[32]);

void ro_hex(const uint8_t *bytes, size_t n, char *out);      /* lower case; out holds 2n + 1 bytes */
int ro_unhex(const char *text, size_t len, uint8_t *out, size_t n);   /* exactly 2n hex digits in len chars; 0 on success */
