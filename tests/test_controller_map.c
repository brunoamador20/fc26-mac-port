/* Test the controller layout parser and mapping (games/totk/runtime/controller_map.h) with synthetic files. */
#include "../games/totk/runtime/controller_map.h"
#include <stdio.h>

enum { SOUTH = 1 << 0, EAST = 1 << 1, WEST = 1 << 2, NORTH = 1 << 3, MENU = 1 << 10 };
enum { A = 1 << 0, B = 1 << 1, X = 1 << 2, Y = 1 << 3, ZR = 1 << 9, PLUS = 1 << 10 };

static int failures;
static void expect(int ok, const char *what) { if (!ok) { fprintf(stderr, "FAIL: %s\n", what); failures++; } }

static uint64_t press(const char *text, uint64_t physical, int *line) {
    uint16_t map[CONTROLLER_BUTTONS]; const char *error = NULL;
    controller_map_default(map);
    *line = controller_map_parse(text, map, &error);
    expect(!*line || error, "a bad line names its problem");
    return controller_map_apply(map, physical);
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
    if (failures) return 1;
    printf("PASS: controller layout cases\n");
    return 0;
}
