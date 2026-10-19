/* Test the controller layout parser and mapping (games/totk/runtime/controller_map.h) with synthetic files. */
#include "../games/totk/runtime/controller_map.h"
#include <stdio.h>

enum { SOUTH = 1 << 0, EAST = 1 << 1, WEST = 1 << 2, NORTH = 1 << 3, MENU = 1 << 10 };
enum { A = 1 << 0, B = 1 << 1, X = 1 << 2, Y = 1 << 3, ZR = 1 << 9, PLUS = 1 << 10 };

static int failures;
static void expect(int ok, const char *what) { if (!ok) { fprintf(stderr, "FAIL: %s\n", what); failures++; } }

static uint64_t press(const char *text, uint64_t physical, int *line) {
    uint16_t map[CONTROLLER_BUTTONS]; uint8_t modes[CONTROLLER_BUTTONS]; const char *error = NULL;
    controller_map_default(map, modes);
    *line = controller_map_parse(text, map, modes, &error);
    expect(!*line || error, "a bad line names its problem");
    return controller_map_apply(map, physical);
}

/* The mode and target of one physical button after parsing text, or -1 with *line set. */
static int mode_of(const char *text, int physical, int *line) {
    uint16_t map[CONTROLLER_BUTTONS]; uint8_t modes[CONTROLLER_BUTTONS]; const char *error = NULL;
    controller_map_default(map, modes);
    *line = controller_map_parse(text, map, modes, &error);
    return *line ? -1 : modes[physical];
}

int main(void) {
    int line;
    expect(press("", SOUTH | EAST | WEST | NORTH | MENU, &line) == (A | B | X | Y | PLUS) && !line, "no lines: default layout");
    uint64_t nintendo = press("# buttons by position, as on a Switch\neast = a\nsouth = b\nnorth = x\nwest = y\n", SOUTH, &line);
    expect(nintendo == B && !line, "south drives B in the Nintendo layout");
    expect(press("east = a\nsouth = b\nnorth = x\nwest = y", EAST | NORTH, &line) == (A | X) && !line, "last line without a newline");
    expect(press("  SOUTH\t=  ZR  \r\n\r\n", SOUTH, &line) == ZR && !line, "spaces, tabs, CRLF and upper case");
    expect(press("south = a # trailing comment\neast = a\n", SOUTH | EAST, &line) == A && !line, "two buttons may drive one Switch button");
    expect(press("menu = none\n", MENU | SOUTH, &line) == A && !line, "none leaves a button unused");
    expect(press("north = a\nnorth = b\n", NORTH, &line) == B && !line, "a later line for the same button wins");
    expect(press("east = a\nsout = b\n", SOUTH, &line) == A && line == 2, "unknown controller button: line 2, layout unchanged");
    expect(press("south = c\n", SOUTH, &line) == A && line == 1, "unknown Switch button");
    expect(press("south =\n", SOUTH, &line) == A && line == 1, "missing Switch button");
    expect(press("\n# note\nsouth b\n", SOUTH, &line) == A && line == 3, "missing equals sign");
    expect(press("= a\n", SOUTH, &line) == A && line == 1, "missing controller button");
    expect(mode_of("south = x tap\n", 0, &line) == CONTROLLER_TAP && !line, "tap mode");
    expect(mode_of("l3 = b TOGGLE\n", 4, &line) == CONTROLLER_TOGGLE && !line, "toggle mode, upper case");
    expect(mode_of("south = b hold\n", 0, &line) == CONTROLLER_HOLD && !line, "hold mode");
    expect(mode_of("south = b\n", 0, &line) == CONTROLLER_HOLD && !line, "no mode: hold");
    expect(mode_of("south = b tap extra\n", 0, &line) == -1 && line == 1, "two modes");
    expect(mode_of("south = b turbo\n", 0, &line) == -1 && line == 1, "unknown mode");
    expect(mode_of("menu = none tap\n", 10, &line) == -1 && line == 1, "none takes no mode");
    expect(mode_of("l2 = zr aim r2\n", 8, &line) == (CONTROLLER_AIM | 9 << 4) && !line, "aim with its fire button");
    expect(mode_of("l2 = zr aim\n", 8, &line) == -1 && line == 1, "aim without a fire button");
    expect(mode_of("l2 = zr aim l2\n", 8, &line) == -1 && line == 1, "aim fired by itself");
    expect(mode_of("l2 = zr aim r2 extra\n", 8, &line) == -1 && line == 1, "aim with an extra word");
    if (failures) return 1;
    printf("PASS: controller layout cases\n");
    return 0;
}
