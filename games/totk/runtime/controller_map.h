/* Controller button layout: each physical button of a Mac controller (named by its position, the same on a DualSense and an
   Xbox controller) drives one Switch Pro Controller button, or none. Physical button i is FullKey bit i of the default
   layout, so the default map is the identity: south -> A, east -> B, west -> X, north -> Y, as macOS names them.
   A layout file has one "physical = switch" line per change; '#' starts a comment; names are case-insensitive; "none"
   leaves a button unused; lines not given keep the default. Pure C: app/launcher.m checks the file before the game
   starts (an alert names the bad line), runtime/gamepad.m applies it, tests/test_controller_map.c covers the parser. */
#ifndef TOTK_CONTROLLER_MAP_H
#define TOTK_CONTROLLER_MAP_H
#include <stdint.h>
#include <string.h>
#include <strings.h>

enum { CONTROLLER_BUTTONS = 16 };
static const char *const controller_physical_names[CONTROLLER_BUTTONS] = {
    "south", "east", "west", "north", "l3", "r3", "l1", "r1", "l2", "r2", "menu", "view", "left", "up", "right", "down"};
static const char *const controller_switch_names[CONTROLLER_BUTTONS] = {
    "a", "b", "x", "y", "lstick", "rstick", "l", "r", "zl", "zr", "plus", "minus", "left", "up", "right", "down"};

static inline void controller_map_default(uint16_t map[CONTROLLER_BUTTONS]) {
    for (int i = 0; i < CONTROLLER_BUTTONS; i++) map[i] = (uint16_t)(1u << i);
}

/* Index of name [s, s + n) in names, or -1. */
static inline int controller_name_index(const char *const names[CONTROLLER_BUTTONS], const char *s, size_t n) {
    for (int i = 0; i < CONTROLLER_BUTTONS; i++)
        if (strlen(names[i]) == n && !strncasecmp(names[i], s, n)) return i;
    return -1;
}

/* Applies a layout file's text to map (start from controller_map_default). Returns 0, or the 1-based number of the first
   bad line with *error naming the problem; map is then unchanged. */
static inline int controller_map_parse(const char *text, uint16_t map[CONTROLLER_BUTTONS], const char **error) {
    uint16_t next[CONTROLLER_BUTTONS];
    memcpy(next, map, sizeof next);
    int line = 0;
    for (const char *p = text; p && *p;) {
        line++;
        const char *end = strchr(p, '\n'), *stop = end ? end : p + strlen(p), *hash = memchr(p, '#', (size_t)(stop - p));
        if (hash) stop = hash;
        while (p < stop && (*p == ' ' || *p == '\t' || *p == '\r')) p++;
        while (stop > p && (stop[-1] == ' ' || stop[-1] == '\t' || stop[-1] == '\r')) stop--;
        if (p < stop) {
            const char *eq = memchr(p, '=', (size_t)(stop - p));
            if (!eq) { *error = "expected \"button = Switch button\""; return line; }
            const char *key_end = eq, *value = eq + 1;
            while (key_end > p && (key_end[-1] == ' ' || key_end[-1] == '\t')) key_end--;
            while (value < stop && (*value == ' ' || *value == '\t')) value++;
            int physical = controller_name_index(controller_physical_names, p, (size_t)(key_end - p));
            if (physical < 0) { *error = "unknown controller button (south east west north l1 r1 l2 r2 l3 r3 menu view up down left right)"; return line; }
            size_t n = (size_t)(stop - value);
            int target = n == 4 && !strncasecmp(value, "none", 4) ? CONTROLLER_BUTTONS : controller_name_index(controller_switch_names, value, n);
            if (target < 0) { *error = "unknown Switch button (a b x y l r zl zr plus minus lstick rstick up down left right none)"; return line; }
            next[physical] = target == CONTROLLER_BUTTONS ? 0 : (uint16_t)(1u << target);
        }
        p = end ? end + 1 : NULL;
    }
    memcpy(map, next, sizeof next);
    return 0;
}

/* The Switch buttons held, from the physical buttons held (bit i = physical button i). */
static inline uint64_t controller_map_apply(const uint16_t map[CONTROLLER_BUTTONS], uint64_t physical) {
    uint64_t buttons = 0;
    for (int i = 0; i < CONTROLLER_BUTTONS; i++)
        if (physical >> i & 1) buttons |= map[i];
    return buttons;
}
#endif
